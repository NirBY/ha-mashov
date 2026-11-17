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

# Mailbox attachment samples: synthetic ids; the Hebrew name exercises Unicode paths.
TEST_ENTRY_ID = "entry"
TEST_CONVERSATION_ID = "11111111-2222-3333-4444-555555555555"
TEST_OTHER_CONVERSATION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TEST_MESSAGE_ID = "99999999-8888-7777-6666-555555555555"
TEST_FILE_ID = "4242"
TEST_FILE_NAME = "תמונה של הכיתה.png"
TEST_FILE_BYTES = b"synthetic image bytes"
TEST_FILE_CONTENT_TYPE = "image/png; charset=binary"
