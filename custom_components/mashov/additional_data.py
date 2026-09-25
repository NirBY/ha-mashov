"""Optional, read-only student resources exposed by the Mashov parent portal."""

from dataclasses import dataclass

CONF_ADDITIONAL_DATA = "additional_data"


@dataclass(frozen=True)
class StudentResource:
    name: str
    path: str
    dated: bool = False


STUDENT_RESOURCES = {
    "message_board": StudentResource("Noticeboard", "messageBoard"),
    "daily_behavior": StudentResource("Daily Behavior", "dailyBehave", True),
    "outside_behavior": StudentResource("Outside Lesson Behavior", "outBehave", True),
    "follow_up": StudentResource("Follow-up Notes", "maakav", True),
    "periodic_grades": StudentResource("Term Grades", "periodic"),
    "report_cards": StudentResource("Report Cards", "reportCards"),
    "study_materials": StudentResource("Study Materials", "studyFiles"),
    "student_files": StudentResource("Student Files", "files"),
    "justification_requests": StudentResource("Absence Justification Requests", "justificationrequests", True),
}
