"""Sample credentials and Mashov API payloads shared by the tests.

Values match the ``mock_config_entry`` and ``mock_mashov_client`` fixtures in conftest.
"""

# Test credentials
TEST_USERNAME = "test_user"
TEST_PASSWORD = "test_password"
TEST_SCHOOL_ID = "123456"
TEST_SCHOOL_NAME = "Test School"
TEST_YEAR = "2024"

# Test student data
TEST_STUDENT = {
    "childGuid": "student-123",
    "privateName": "Test",
    "lastName": "Student",
    "fullName": "Test Student",
}

# Test homework data
TEST_HOMEWORK = [
    {
        "lessonId": "lesson-1",
        "lesson_date": "2024-01-15T00:00:00",
        "lesson": 1,
        "groupId": "group-1",
        "subject_name": "Mathematics",
        "homework": "Page 10-15",
    }
]

# Test behavior data
TEST_BEHAVIOR = [
    {
        "lesson_date": "2024-01-15T00:00:00",
        "lesson": 1,
        "subject": "Mathematics",
        "achva_name": "Excellent participation",
        "teacher_name": "Test Teacher",
    }
]

# Test timetable data
TEST_TIMETABLE = [
    {
        "timeTable": {"day": 1, "lesson": 1, "groupId": "group-1"},
        "groupDetails": {"subjectName": "Mathematics", "groupName": "Math A"},
        "groupTeachers": [{"teacherName": "Test Teacher"}],
    }
]

# Test weekly plan data
TEST_WEEKLY_PLAN = [
    {
        "lesson_date": "2024-01-15T00:00:00",
        "lesson": 1,
        "group_id": "group-1",
        "plan": "Introduction to algebra",
    }
]

# Test holidays data
TEST_HOLIDAYS = [
    {
        "start": "2024-01-20T00:00:00",
        "end": "2024-01-21T00:00:00",
        "name": "Test Holiday",
    }
]

# Parent approvals (synthetic; shapes follow the parent-portal GET list routes).
TEST_APPROVALS_NOW = "2026-11-17T12:00:00"
TEST_CHILD_A = "child-guid-a"
TEST_CHILD_B = "child-guid-b"
TEST_PARENT_GUID = "parent-guid"
TEST_CREATOR_GUID = "creator-guid"
TEST_ACTIVITY_TITLE = "Synthetic trip"
TEST_OPEN_ACTIVITY = {
    "id": 101,
    "createTime": "2026-11-01T09:00:00",
    "activityStartDate": "2026-11-25T08:00:00",
    "activityEndDate": "2026-11-25T14:00:00",
    "activityType": 1,
    "creatorGuid": TEST_CREATOR_GUID,
    "title": TEST_ACTIVITY_TITLE,
    "description": "<p>Bring <b>water</b></p><script>steal()</script>",
    "endAnswerDate": "2026-11-20T23:59:00",
    "isAnswered": False,
}
# Deadline passed two days ago: still inside the answers lookback.
TEST_RECENT_EXPIRED_ACTIVITY = {
    **TEST_OPEN_ACTIVITY,
    "id": 102,
    "activityType": 4,
    "endAnswerDate": "2026-11-15T12:00:00",
}
# Deadline passed long ago: no answers request at all.
TEST_OLD_ACTIVITY = {**TEST_OPEN_ACTIVITY, "id": 103, "activityType": 9, "endAnswerDate": "2026-09-01T12:00:00"}
TEST_MALFORMED_ACTIVITIES = ["not a record", {"title": "no id"}, {"id": True, "title": "bool id"}, {"id": 104}]
TEST_LATER_ACTIVITY = {**TEST_OPEN_ACTIVITY, "id": 105, "endAnswerDate": "2026-11-28T08:00:00"}


def user_answer(student_guid, answer, activity_id=TEST_OPEN_ACTIVITY["id"]):
    """One userAnswers entry; answer=... omits the field entirely."""
    entry = {"activityId": activity_id, "userId": TEST_PARENT_GUID, "studentGuid": student_guid}
    if answer is not ...:
        entry["answer"] = answer
    return {"userId": TEST_PARENT_GUID, "schoolActivityAnswer": entry}


TEST_FORM_TITLE = "Synthetic consent form"
TEST_CONSENT_FORM = {
    "formId": 7,
    "formData": '{"title": "Synthetic consent form", "questions": [{"isMust": true}, {"isMust": false}]}',
    "createTime": "2026-11-10T08:00:00",
    "endTime": "2026-11-30T00:00:00",
    "isAnswered": False,
}
TEST_INVALID_FORM_DATA = "{not json"
TEST_ANSWERED_FORM = {**TEST_CONSENT_FORM, "formId": 8, "isAnswered": True}
TEST_EXPIRED_FORM = {**TEST_CONSENT_FORM, "formId": 9, "endTime": "2026-11-01T00:00:00"}
# A normalized pending record, as stored in coordinator data.
TEST_PENDING_RECORD = {
    "activity_id": 101,
    "title": TEST_ACTIVITY_TITLE,
    "type": "trip",
    "description": "",
    "start": None,
    "end": None,
    "answer_deadline": "2026-11-20T23:59:00+02:00",
    "expired": False,
    "status": "pending",
}
