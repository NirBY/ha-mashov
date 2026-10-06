"""Optional, read-only student resources exposed by the Mashov parent portal.

Users choose these per config entry through "enabled_data". The legacy
"additional_data" option remains supported when upgrading older entries.
"""

from dataclasses import dataclass

# Options key holding the list of STUDENT_RESOURCES keys the user enabled.
CONF_ADDITIONAL_DATA = "additional_data"


@dataclass(frozen=True)
class StudentResource:
    """Description of one optional per-student portal endpoint.

    name:  English display name (UI labels come from the translations instead).
    path:  Last segment of the portal's per-student API URL.
    dated: True when the endpoint expects a date range in the request.
    """

    name: str
    path: str
    dated: bool = False


# Option key -> resource. The keys are stable identifiers: they are stored in
# config entry options, used as translation keys for the options selector, and
# counted by name in diagnostics (reporting.py only exports keys found here).
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
    "special_hours": StudentResource("Individual Lessons", "specialHoursLessons"),
}
