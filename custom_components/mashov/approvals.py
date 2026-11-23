"""Parent approvals: school activities (trips) and online forms.

Refreshes only send GET requests. Answering an activity (PUT) happens only from the
admin service answer_school_activity, and only with the hub option
allow_approval_answers on. Forms and the digital-approval declaration are never written.
"""

from copy import deepcopy
from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

from .mailbox import plain_body

PARENT_APPROVALS = "parent_approvals"
ANSWERS_KEY = "activity_answers"
ACTIVITIES_PATH = "schoolActivities/permitted"
ANSWERS_PATH = "schoolActivities/{activity_id}/userAnswers"
FORMS_PATH = "user/forms?isParentsConsent={consent}"
DETAIL_PATH = "schoolActivities/{activity_id}/permitted"
DETAIL_KEY = "activity_detail"
# The portal's own answer request (updateUserSchoolActivityAnswer in the web app).
ANSWER_PATH = "students/{student_id}/schoolActivities/{activity_id}"
# Mashov sends school-local times without a zone; never assume the host timezone.
SCHOOL_TIME_ZONE = ZoneInfo("Asia/Jerusalem")
# Answers are still fetched this many days after the answer deadline, so a late
# change is shown, while older activities cost no requests.
ANSWERS_LOOKBACK_DAYS = 7
DESCRIPTION_MAX_CHARS = 300

STATUS_PENDING = "pending"
STATUS_UNKNOWN = "unknown"
ANSWER_STATUSES = {1: "approved", 2: "approved_with_conditions", 3: "denied"}
ANSWER_CODES = {status: code for code, status in ANSWER_STATUSES.items()}
ACTIVITY_TYPES = {1: "trip", 4: "culture_basket"}
DEFAULT_ACTIVITY_TYPE = "school_activity"
FORM_KINDS = {"consent": "true", "general": "false"}


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_time(value, zone):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed


def _iso(value):
    return value.isoformat() if value else None


def _activity(raw, now, zone):
    """Normalize one list item, or None when it lacks an id or title."""
    if not isinstance(raw, dict) or not _is_int(raw.get("id")) or not isinstance(raw.get("title"), str):
        return None
    deadline = _parse_time(raw.get("endAnswerDate"), zone)
    description = raw.get("description")
    return {
        "activity_id": raw["id"],
        "title": raw["title"],
        "type": ACTIVITY_TYPES.get(raw.get("activityType"), DEFAULT_ACTIVITY_TYPE),
        "description": plain_body(description)[:DESCRIPTION_MAX_CHARS] if isinstance(description, str) else "",
        "start": _iso(_parse_time(raw.get("activityStartDate"), zone)),
        "end": _iso(_parse_time(raw.get("activityEndDate"), zone)),
        "answer_deadline": _iso(deadline),
        "expired": bool(deadline and now > deadline),
        "within_bound": deadline is None or now - deadline <= timedelta(days=ANSWERS_LOOKBACK_DAYS),
        "is_answered": raw.get("isAnswered") is True,
    }


def answer_status(answer):
    """Map a schoolActivityAnswer.answer value; missing or null means pending."""
    if answer is None:
        return STATUS_PENDING
    return ANSWER_STATUSES.get(answer, STATUS_UNKNOWN) if _is_int(answer) else STATUS_UNKNOWN


def _known_child(known, *values):
    for value in values:
        if isinstance(value, str) and value.lower() in known:
            return known[value.lower()]
    return None


def _answers_by_child(payload, student_ids):
    """Return {student_id: status} for this account's children only.

    An answered row nests the child in ``schoolActivityAnswer.studentGuid``. An unanswered
    row omits that object and puts the child in the top-level ``userId`` instead.
    """
    known = {str(sid).lower(): sid for sid in student_ids}
    result = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        answer = entry.get("schoolActivityAnswer")
        if isinstance(answer, dict):
            sid = _known_child(
                known,
                answer.get("studentGuid"),
                answer.get("userId"),
                entry.get("studentGuid"),
                entry.get("userId"),
            )
            status = answer_status(answer.get("answer"))
        else:
            sid = _known_child(known, entry.get("studentGuid"), entry.get("userId"))
            status = STATUS_PENDING
        if sid is not None:
            result[sid] = status
    return result


def _public(record, status):
    item = {key: value for key, value in record.items() if key not in ("within_bound", "is_answered")}
    item["status"] = status
    return item


async def _assign(get_json, record, student_ids, result):
    """Split one activity into per-child records; unattributed open ones go to "unassigned"."""
    path = ANSWERS_PATH.format(activity_id=record["activity_id"])
    status, payload = await get_json(path, ANSWERS_KEY, list)
    answers = _answers_by_child(payload, student_ids) if status == "ok" else {}
    for sid, answer in answers.items():
        result["by_student"].setdefault(sid, []).append(_public(record, answer))
    if status != "ok":
        result["answers_failures"] += 1
    # Answered per the list and confirmed with no child of ours: nothing is open.
    if answers or record["expired"] or (record["is_answered"] and status == "ok"):
        return
    fallback = STATUS_UNKNOWN if record["is_answered"] else STATUS_PENDING
    result["unassigned"].append(_public(record, fallback))


def _form(raw, now, zone):
    """Normalize one form; an unreadable formData only loses the question count."""
    if not isinstance(raw, dict) or not (_is_int(raw.get("formId")) or isinstance(raw.get("formId"), str)):
        return None
    try:
        form_data = json.loads(raw.get("formData") or "")
    except (TypeError, ValueError):
        form_data = None
    form_data = form_data if isinstance(form_data, dict) else {}
    questions = form_data.get("questions")
    title = next((v for v in (raw.get("title"), form_data.get("title")) if isinstance(v, str)), None)
    deadline = _parse_time(raw.get("endTime"), zone)
    return {
        "title": title,
        "deadline": _iso(deadline),
        "created": _iso(_parse_time(raw.get("createTime"), zone)),
        "expired": bool(deadline and now > deadline),
        "answered": raw.get("isAnswered") is True,
        "question_count": len(questions) if isinstance(questions, list) else None,
    }


async def _fetch_forms(get_json, result, now, zone):
    for kind, consent in FORM_KINDS.items():
        status, payload = await get_json(FORMS_PATH.format(consent=consent), f"{kind}_forms", list)
        result["forms_status"][kind] = status
        forms = (_form(raw, now, zone) for raw in payload) if status == "ok" else ()
        result["forms"][kind] = [form for form in forms if form is not None]


async def fetch_parent_approvals(get_json, student_ids, now=None):
    """Fetch activities, bounded per-activity answers and both form lists, once per account.

    get_json returns (status, payload) and owns authentication, backoff and
    failure isolation; a failed route only leaves its own part empty.
    """
    zone = SCHOOL_TIME_ZONE
    now = now or datetime.now(zone)
    result = {"by_student": {}, "unassigned": [], "answers_failures": 0, "forms": {}, "forms_status": {}}
    status, payload = await get_json(ACTIVITIES_PATH, PARENT_APPROVALS, list)
    result["status"] = status
    records = (_activity(raw, now, zone) for raw in payload) if status == "ok" else ()
    for record in records:
        if record is not None and record["within_bound"]:
            await _assign(get_json, record, student_ids, result)
    await _fetch_forms(get_json, result, now, zone)
    return result


def _deadline_order(item):
    deadline = item.get("answer_deadline", item.get("deadline"))
    return (deadline is None, deadline or "")


def open_pending(records):
    """Pending, still answerable activities, earliest deadline first."""
    pending = [deepcopy(r) for r in records if r.get("status") == STATUS_PENDING and not r.get("expired")]
    return sorted(pending, key=_deadline_order)


def open_forms(forms):
    """Unanswered forms whose due date has not passed, earliest deadline first."""
    return sorted((deepcopy(f) for f in forms if not f.get("answered") and not f.get("expired")), key=_deadline_order)


def pending_summary(resource, students):
    """Pending items for Assist/MCP: title, child name, deadline and status; never ids."""
    names = {student["id"]: student.get("name") for student in students}
    items = [
        {"title": r["title"], "child": names.get(sid), "deadline": r["answer_deadline"], "status": r["status"]}
        for sid, records in resource.get("by_student", {}).items()
        for r in open_pending(records)
    ]
    items += [
        {"title": r["title"], "child": None, "deadline": r["answer_deadline"], "status": r["status"]}
        for r in open_pending(resource.get("unassigned", []))
    ]
    items += [
        {"title": f["title"], "child": None, "deadline": f["deadline"], "status": STATUS_PENDING}
        for kind in FORM_KINDS
        for f in open_forms(resource.get("forms", {}).get(kind, []))
    ]
    return sorted(items, key=_deadline_order)


def display_activities(records, *, show_ended, hide_answered, newest_first, now=None):
    """The portal's list toggles, applied to one child's fetched activities (display only)."""
    now = now or datetime.now(SCHOOL_TIME_ZONE)

    def ended(record):
        end = _parse_time(record.get("end"), SCHOOL_TIME_ZONE)
        return bool(end and now > end)

    shown = [
        deepcopy(r)
        for r in records
        if (show_ended or not ended(r)) and not (hide_answered and r.get("status") in ANSWER_CODES)
    ]
    return sorted(shown, key=lambda r: r.get("start") or "", reverse=newest_first)


def answer_refusal(detail, answers, activity_id, student_id, now=None):
    """Why this answer must not be sent, from data fetched just now; None when it may be sent.

    detail is the GET schoolActivities/<id>/permitted payload and answers the matching
    userAnswers payload. Both are read right before the PUT, so a deadline that passed
    after the last refresh is still seen.
    """
    now = now or datetime.now(SCHOOL_TIME_ZONE)
    activity = detail[0] if detail and isinstance(detail[0], dict) else None
    if activity is None or activity.get("id") != activity_id:
        return "unknown_activity"
    deadline = _parse_time(activity.get("endAnswerDate"), SCHOOL_TIME_ZONE)
    if deadline is None:
        # Fail closed: a write is never sent when the deadline cannot be checked.
        return "deadline_unknown"
    if now > deadline:
        return "deadline_passed"
    data = activity.get("activityData")
    if data is not None and not (isinstance(data, str) and not data.strip()):
        # A questionnaire needs answerData built from its questions; not supported here.
        return "has_questions"
    if student_id not in _answers_by_child(answers, [student_id]):
        return "student_not_covered"
    return None


def answer_body(activity_id, student_id, parent_user_id, status, remark):
    """The PUT body the portal sends for an activity without questions."""
    return {
        "activityId": activity_id,
        "studentGuid": student_id,
        "userId": parent_user_id,
        "answer": ANSWER_CODES[status],
        "remark": remark,
    }
