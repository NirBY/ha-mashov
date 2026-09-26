"""Constants shared across the Mashov integration (config keys, defaults, sensor keys)."""

from __future__ import annotations

DOMAIN = "mashov"

# --- Config entry data (set by the config flow) ---
CONF_SCHOOL_ID = "school_id"
CONF_SCHOOL_NAME = "school_name"
# Frozen school year. Absent/empty means the year follows the calendar automatically;
# stored when the user turns the automatic school year off (see configured_school_year).
CONF_YEAR = "year"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
# CONF_STUDENT_NAME removed: all students of the account are discovered automatically.

# --- Options (Configure UI, set_options service or YAML) ---
CONF_HOMEWORK_DAYS_BACK = "homework_days_back"
CONF_HOMEWORK_DAYS_FORWARD = "homework_days_forward"
CONF_API_BASE = "api_base"
CONF_SCHEDULE_TYPE = "schedule_type"  # "daily", "weekly", "interval"
CONF_SCHEDULE_TIME = "schedule_time"  # "HH:MM" (or "HH:MM:SS") for daily/weekly
CONF_SCHEDULE_DAY = "schedule_day"  # legacy single weekday 0-6 (0=Monday); migrated to schedule_days
CONF_SCHEDULE_DAYS = "schedule_days"  # list of weekdays 0-6 (0=Monday) for weekly
CONF_SCHEDULE_INTERVAL = "schedule_interval"  # minutes for interval

PLATFORMS = ["sensor", "calendar"]

# --- Defaults ---
DEFAULT_HOMEWORK_DAYS_BACK = 7
DEFAULT_HOMEWORK_DAYS_FORWARD = 21
DEFAULT_API_BASE = "https://web.mashov.info/api/"
DEFAULT_SCHEDULE_TYPE = "daily"
DEFAULT_SCHEDULE_TIME = "14:00"
DEFAULT_SCHEDULE_DAY = 0  # Monday
DEFAULT_SCHEDULE_INTERVAL = 60  # 60 minutes

# --- Sensor attribute size limits ---
# Maximum items to store in sensor attributes (to avoid DB size issues).
# Full data is always available via coordinator.data.
# Note: Actual size is checked dynamically - this is a starting point before size verification.
CONF_MAX_ITEMS_IN_ATTRIBUTES = "max_items_in_attributes"
DEFAULT_MAX_ITEMS_IN_ATTRIBUTES = 100  # Starting point; actual count limited by 14KB size check

# --- Sensor keys (also used in unique IDs; changing them orphans entities) ---
SENSOR_KEY_HOMEWORK = "homework"
SENSOR_KEY_BEHAVIOR = "behavior"
SENSOR_KEY_WEEKLY_PLAN = "weekly_plan"
SENSOR_KEY_TIMETABLE = "timetable"
SENSOR_KEY_LESSONS_HISTORY = "lessons_history"
SENSOR_KEY_GRADES = "grades"
SENSOR_KEY_HOLIDAYS = "holidays"

# --- Device registry metadata ---
DEVICE_MANUFACTURER = "Mashov (Unofficial)"
DEVICE_MODEL = "Mashov Student Data"
