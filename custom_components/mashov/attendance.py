"""Normalize the parent portal's per-group behavior counters without student profiles."""

ATTENDANCE_COUNTS = "attendance_counts"
TOTAL_FIELDS = (
    "absences",
    "lateness",
    "justified_absences",
    "unjustified_absences",
    "justified_lateness",
    "unjustified_lateness",
    "other_events",
    "unclassified_events",
    "total_events",
)
METADATA_FIELDS = (
    *TOTAL_FIELDS,
    "classification_complete",
    "lessons_count",
    "school_year",
    "period_start",
    "period_end",
)


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError("Invalid attendance count")
    return value


def normalize_attendance(payload, definitions, groups, student_id, year):
    """Use the school's common-behavior mapping, never its arbitrary event codes.

    Canonical Mashov commonBehaveBank IDs: 1 absence, 3 lateness, 16 online
    absence. Unmapped school events stay visible without guessing from names.
    A successful empty list means no events; a foreign student's envelope is
    rejected, including a response that mixes the requested student with others.
    """
    if not all(
        isinstance(rows, list) and all(isinstance(row, dict) for row in rows) for rows in (payload, definitions, groups)
    ):
        raise ValueError("Invalid attendance response")
    types = {}
    for definition in definitions:
        code, common = definition.get("code"), definition.get("commonBehaveId")
        if type(code) is not int or (common is not None and type(common) is not int) or code in types:
            raise ValueError("Invalid attendance definitions")
        types[code] = common
    by_group = {}

    def group_row(group_id, subject=None, name=None):
        if type(group_id) is not int:
            raise ValueError("Invalid attendance group")
        return by_group.setdefault(
            group_id,
            {
                "group_id": group_id,
                "subject": subject,
                "group_name": name,
                **dict.fromkeys(TOTAL_FIELDS, 0),
                "events": [],
            },
        )

    for group in groups:
        group_row(group.get("groupId"), group.get("subjectName"), group.get("groupName"))
    lessons_count = 0
    # The scoped endpoint returns at most one envelope. Reject duplicates rather
    # than counting the same student's events twice.
    if len(payload) > 1:
        raise ValueError("Unexpected attendance students")
    for envelope in payload:
        student = envelope.get("student")
        if not isinstance(student, dict) or str(student.get("studentGuid", "")).lower() != str(student_id).lower():
            raise ValueError("Unexpected attendance student")
        lessons_count += _count(envelope.get("lessonsCount"))
        events = envelope.get("eventsCount")
        if not isinstance(events, list):
            raise ValueError("Invalid attendance events")
        seen = set()
        for event in events:
            if not isinstance(event, dict) or type(event.get("eventCode")) is not int:
                raise ValueError("Invalid attendance event")
            row = group_row(event.get("groupId"))
            identity = (event["groupId"], event["eventCode"])
            if identity in seen:
                raise ValueError("Duplicate attendance event")
            seen.add(identity)
            justified, unjustified = _count(event.get("justified")), _count(event.get("notJustified"))
            total = justified + unjustified
            common = types.get(event["eventCode"])
            category = (
                "absences"
                if common in (1, 16)
                else "lateness"
                if common == 3
                else "unclassified_events"
                if common is None
                else "other_events"
            )
            row[category] += total
            row["total_events"] += total
            if category in ("absences", "lateness"):
                row[f"justified_{category}"] += justified
                row[f"unjustified_{category}"] += unjustified
            row["events"].append(
                {
                    "event_code": event["eventCode"],
                    "name": event.get("eventName"),
                    "common_behave_id": common,
                    "category": category,
                    "total": total,
                    "justified": justified,
                    "unjustified": unjustified,
                }
            )
    items = list(by_group.values())
    totals = {key: sum(item[key] for item in items) for key in TOTAL_FIELDS}
    return {
        "status": "ok",
        "items": items,
        **totals,
        "classification_complete": totals["unclassified_events"] == 0,
        "lessons_count": lessons_count,
        "school_year": year,
        "period_start": f"{year - 1}-09-01",
        "period_end": f"{year}-08-31",
    }
