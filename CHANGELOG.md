# Changelog

## [Unreleased]

## [1.0.5] - 2026-01-20

### Fixed
- **Authentication Race Condition**: Fixed a critical issue where concurrent requests (e.g., initial load) would trigger multiple parallel login attempts. (Fixes #4, #5)
- **Login Stabilization**: Added `asyncio.Lock` to ensure only one re-login attempt occurs at a time.
- **Session Validation**: Implemented smart session validation to prevent redundant re-logins if a valid session was established recently (debounce).
- **Log Spam**: Eliminated excessive "401 on ... attempting re-login..." warnings in logs.
- **Performance**: Improved update speed by ~4x (from ~13s to ~3s) by eliminating wasted requests and redundant re-authentications.

## [1.0.4] - 2025-10-27

### Fixed
- **Critical bug** in calendar.py - Fixed operator precedence that could cause crash when finding next holiday
- **Grades sensor** formatting - Added proper display formatting (by_date, by_subject, with average calculation)
- **Grades data cleaning** - Now removes redundant technical fields (gradingEventId, gradeTypeId, etc.)

### Changed
- Updated README with @aviadlevy credit for calendar contribution

## [1.0.3] - 2025-10-24

### Added
- **Grades sensor** - New sensor for student grades (`sensor.mashov_<student_id>_grades`)
  - Displays grade, grading event, teacher name, subject, grade type
  - Includes event date, grading period, and textual grades
  - Full integration with size-based limiting (14KB target)
- **Calendar entity** - Holidays calendar integration for Home Assistant calendar view
  - Contributed by @aviadlevy

## [1.0.2] - 2025-10-24

### Fixed
- **[Bug #2]** Fixed state attributes exceeding maximum size of 16384 bytes
  - Removed redundant technical fields (GUIDs, codes, IDs) from stored items, saving 15-45% space
  - Intelligent size-based limiting (14KB target with 2KB safety margin)
  - Binary search algorithm to find optimal item count that fits within size limit
  - User-configurable max items (10-500, default: 100) as starting point before size verification
  - All data remains available via `coordinator.data` for automations and templates
  - Added `total_items` and `stored_items` attributes to show full count vs. stored count
  - Added configuration option `max_items_in_attributes` in integration options

### Changed
- Optimized sensor attribute storage: removed technical fields (studentGuid, reporterGuid, eventCode, etc.)
- `items` attribute contains cleaned, size-optimized recent items (2x more items can fit now)
- Improved storage efficiency: Behavior 45%, Timetable 26%, Lessons 14% size reduction
- Logs info when size limit triggers automatic item count adjustment

## [1.0.1] - 2025-10-18

### Added
- Full test suite with pytest and pytest-homeassistant-custom-component
- GitHub Actions CI/CD pipeline for automated testing and linting
- HACS validation in CI/CD workflow
- Ruff linting and formatting configuration
- Pre-commit hooks configuration
- Dev container configuration for consistent development environment
- Contributing guidelines (CONTRIBUTING.md)
- Test fixtures and comprehensive test coverage for config_flow, sensors, and init

### Changed
- Improved test infrastructure and coverage (52% overall, 72% for sensors)
- Enhanced code quality with automated linting and formatting

### Fixed
- Fixed `async_unload_entry` to handle cases where setup was mocked or failed
- Fixed config_flow tests to prevent network calls and thread lingering issues
- Fixed sensor tests entity_id format (using student name instead of childGuid)

## [1.0.0] - 2025-10-18

### Changed
- Blueprints: שיפור תזמון TTS - ממתין שהרמקול יתחיל לנגן ואז שיהפוך ל-idle לפני שמחזיר את העוצמה
- Blueprints: הוספת אפשרות להגדרת timeout להתחלת וסיום TTS בדף ההגדרות
- `bag_reminder_tomorrow.yaml`: עודכן לגרסה v1.0.32 עם בקרת timeout מתקדמת
- `mashov_daily_homework_announce.yaml`: עודכן לגרסה v1.0.6 עם בקרת timeout מתקדמת

### Fixed
- Blueprints: תיקון בעיית שינוי עוצמה תוך כדי הקראת TTS

## [0.1.61-beta.12] - 2025-10-11 (Pre-release)

### Added
- TBD

### Changed
- Blueprints: הדפסת טקסט TTS גם במסלולי Skip עבור `bag_reminder_tomorrow.yaml` ו-`mashov_daily_homework_announce.yaml`.

### Fixed
- TBD

## [0.1.61-beta.11] - 2025-10-04 (Pre-release)

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.61-beta.10] - 2025-10-04 (Pre-release)

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.61-beta.9] - 2025-10-04 (Pre-release)

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.61-beta.8] - 2025-10-04 (Pre-release)

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.61-beta.7] - 2025-10-04 (Pre-release)

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.61-beta.6] - 2025-10-04 (Pre-release)

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.61-beta.5] - 2025-10-04 (Pre-release)

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.61-beta.4] - 2025-10-03 (Pre-release)

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.61-beta.3] - 2025-10-03 (Pre-release)

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.61-beta.2] - 2025-10-03 (Pre-release)

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.61-beta.1] - 2025-10-03

### Added
- Translations: Added Options (schedule) UI strings in `translations/he.json` and `translations/en.json`.

### Changed
- Config labels: switched config field label from `school_id` to `school_name` in translations to match the form.

## [0.1.60] - 2025-10-03

### Fixed
- Holidays sensor unique_id made per-entry (`mashov_{entry_id}_holidays`) to avoid duplicates
- Minor debug log for options flow in `__init__.py`

## [0.1.59] - 2025-10-03

### Changed
- הוספת לוג ב-`async_get_options_flow` לזיהוי קריאת ה-Options Flow ב-UI

## [0.1.58] - 2025-10-03

### Changed
- Release workflow: מצרף עכשיו `README.md` ו-`examples/screenshots/**` כרכיבי ריליס אוטומטיים

### Fixed
- README וצילומי מסך הועלו לריפו ונכללים מריליסים חדשים

## [0.1.57] - 2025-10-03

### Added
- הוספת תלות `voluptuous` ל-`manifest.json` כדי לפתור שגיאת ייבוא בסביבת HA

### Fixed
- `config_flow.py`: השתקת type hints עבור ייבואי Home Assistant ו-`voluptuous` כדי לנקות אזהרות IDE
- `__init__.py`: אימות ויישור לינט, ללא שגיאות
- דוגמת Lovelace `weekly_plan_table_advanced.yaml` עודכנה

## [0.1.56] - 2025-10-02

### Added
- Re-introduced Timetable sensor using `/students/{student_id}/timetable` with unified weekly table formatting
- Global Holidays support using `/holidays` endpoint with `sensor.mashov_holidays`
- Lessons History per-student using `/students/{student_id}/lessons/history`
- Exposed `formatted_table_html` attribute for weekly plan/timetable rendering in Markdown cards

### Changed
- README updated to reflect new sensors and to list only existing Lovelace example cards
- `mashov.refresh_now`: calling without `entry_id` now refreshes all hubs (clarified in docs)

### Fixed
- `mashov.refresh_now` no longer raises KeyError when non-entry values (e.g., `yaml_options`) are present in integration data

## [0.1.55] - 2025-10-01

### Added
- Weekly Plan HTML table rendering (`table_html`) + advanced Lovelace Markdown example
- Example Lovelace cards for Homework and Behavior (list-by-date and tables)

### Changed
- README: link to CHANGELOG instead of embedding; clarified Lovelace include paths (`/config/lovelace/cards/examples/`)
- Options UI: replaced advanced selectors with basic types; added YAML overrides support
- Logging and sanitization: clearer scheduler logs and defaults for invalid values

### Removed
- Deprecated `daily_refresh_time` option (use `schedule_time`)

## [0.1.46] - 2025-09-29

## [0.1.47] - 2025-09-29

## [0.1.48] - 2025-09-29

## [0.1.49] - 2025-09-29

## [0.1.50] - 2025-09-29

## [0.1.51] - 2025-09-29

## [0.1.52] - 2025-09-29

## [0.1.53] - 2025-09-29

## [0.1.54] - 2025-09-29

### Fixed
- Options flow compatibility: replaced advanced selectors with basic types so Configure always shows
- Scheduler fallback: honors schedule_time or daily_refresh_time (backward compat)
- Added detailed logs to trace scheduler resolution and options loading

### Changed
- Options UI refined: TimeSelector, multi-day weekly, interval in minutes
- Version bump for HACS update and distribution

### Added
- Options flow wired to Hub (per-entry) via async_get_options_flow

### Fixed
- Scheduler now cancels previous jobs and supports multiple weekly days
- Hub title format updated to "<school name> (<semel>)"

### Fixed
- Removed custom TRACE logger usage to avoid attribute errors in some environments
- Replaced TRACE calls with DEBUG-compatible helper

### Fixed
- Resolved IndentationError in mashov_client.async_open_session causing config flow load failure
- Flow can now be loaded without handler/import errors

### Changed
- Removed city/name splitting heuristic; use `name` from API as-is
- UI labels show only: "<name> (<semel>)"
- Multi-match logic (pick list) preserved when searching by name

### Fixed
- Derive city from school name when API does not include a separate city field
- Labels now show "Name – City (semel)" or "Name (semel)" accordingly

### Added
- Introduced TRACE log level (below DEBUG) across integration
- Converted verbose init/catalog logs to TRACE

### Changed
- Safer label building for schools when city is missing

### Fixed
- Import CONF_SCHEDULE_DAYS in sensor to compute schedule info correctly
- Schedule attributes now populate without errors

## [0.1.45] - 2025-09-29

### Added
- Per-hub (per-entry) scheduling controls in Options
- Weekly mode now supports selecting multiple days + time
- Automatic reschedule on options change (no restart needed)

### Changed
- Default refresh time set to 14:00 daily

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.44] - 2025-09-29

### Fixed
- **Automatic hub title update** - integration now automatically updates hub title on reload
- **School name preservation** - school name is now saved in config data for reliable title updates
- Hub title will automatically fix itself from "413955 413955" to "נעמי שמר פתח תקוה 413955"
- No need to manually reconfigure or reinstall the integration

### Added
- Sensors now expose refresh schedule details in attributes:
  - `schedule_type`, `schedule_time`, `schedule_day`, `schedule_interval_minutes`
  - `schedule_friendly` and `next_scheduled_refresh`

## [0.1.43] - 2025-09-29

### Fixed
- Fixed hub title display issue - now properly shows school name and semel
- Improved title creation logic to preserve school name from cache
- Added debug logging for title creation process

## [0.1.42] - 2025-09-29

### Fixed
- Enhanced homework data formatting to include subject name
- Homework entries now show: "שיעור X - מקצוע: תיאור השיעורים"
- Improved readability by including subject information in formatted output

## [0.1.41] - 2025-09-29

### Fixed
- Changed integration type back to "hub" to display as "school" in Home Assistant
- Fixed hub title format to show school name and semel properly
- Hub title now displays as "נעמי שמר פתח תקוה 413955" instead of "413955 413955"

## [0.1.40] - 2025-09-29

### Added
- Advanced scheduling options for data collection
- Daily, weekly, and interval scheduling modes
- Configurable refresh times and intervals
- Hebrew interface for schedule configuration

### Changed
- Enhanced options flow with new scheduling parameters
- Schedule Type: Daily, Weekly, or Interval-based refresh
- Schedule Time: Specific time for daily/weekly refresh (HH:MM format)
- Schedule Day: Day of week for weekly refresh (Monday-Sunday)
- Schedule Interval: Minutes between refreshes (5-1440 minutes range)

## [0.1.39] - 2025-09-29

### Added
- Enhanced sensor data presentation with formatted summaries
- Added organized data grouping by date and subject
- Improved readability for text-to-speech applications
- Added formatted_summary, formatted_by_date, and formatted_by_subject attributes

### Changed
- Homework data now shows: "שיעור X: תיאור השיעורים"
- Behavior data now shows: "שיעור X - מקצוע: סוג התנהגות (מ-מורה)"
- Weekly plan data now shows: "שיעור X: תיאור התוכנית"
- Dates formatted as DD/MM/YYYY for better readability

## [0.1.38] - 2025-09-29

### Fixed
- Changed integration type from "hub" to "service" for better categorization
- Fixed hub title format to show school name and semel properly
- Hub title now displays as "נעמי שמר פתח תקוה\n413955" instead of "Mashov (413955 - 413955)"

## [0.1.37] - 2025-09-29

### Changed
- Updated behavior data structure to match actual Mashov API response
- Behavior now includes comprehensive event details: event codes, timestamps, lesson info, reporter details, and achievement data
- Improved behavior data accuracy with proper field mapping

## [0.1.36] - 2025-09-29

### Changed
- Updated homework data structure to match actual Mashov API response
- Homework now includes lesson_id, lesson_date, lesson number, group_id, remark, and subject_name
- Improved homework data accuracy and completeness

## [0.1.35] - 2025-09-29

### Added
- Re-added weekly plan sensor with correct endpoint URL
- Weekly plan now uses `/students/{student_id}/lessons/plans` endpoint
- Weekly plan data includes group_id, lesson_date, lesson number, and plan description

### Fixed
- Fixed weekly plan endpoint URL to match Mashov API structure
- Weekly plan now provides actual lesson plans data instead of 404 errors

## [0.1.34] - 2025-09-29

### Removed
- Removed timetable and weekly plan sensors as they don't provide data
- Removed timetable endpoints and related code
- Simplified integration to focus on homework and behavior data only

### Fixed
- Fixed behavior endpoint URL from `/behaviour` to `/behave` to match Mashov API
- Resolved 404 errors for behavior data by using correct endpoint path

## [0.1.33] - 2025-09-29

### Fixed
- Fixed behavior endpoint URL from `/behaviour` to `/behave` to match Mashov API
- Resolved 404 errors for behavior data by using correct endpoint path

## [0.1.32] - 2025-09-29

### Fixed
- Fixed "Failed to load services.yaml for integration: mashov" error
- Added missing services.yaml file with Hebrew service definitions
- Resolved NoneType: None error during integration startup
- Service "רענן נתונים" (refresh_now) now properly defined with Hebrew interface

## [0.1.31] - 2025-09-28

### Fixed
- Fixed authentication logic to properly handle accessToken as dictionary
- Improved version detection with fallback to manifest.json
- Enhanced error handling for authentication flow
- Resolved 'dict' object has no attribute 'startswith' error

## [0.1.30] - 2025-09-28

### Changed
- Enhanced hub display to show both school name and semel number
- Entry title format now shows: "Mashov (נעמי שמר פתח תקוה - 413955)"
- Improved identification by combining school name with semel for better clarity

## [0.1.29] - 2025-09-28

### Fixed
- Fixed hub display to show school name instead of semel number
- Improved school name extraction from school choices during configuration
- Enhanced entry title to display proper school name in Home Assistant

### Changed
- School selection now properly stores and displays school name instead of semel
- Entry title format changed from "Mashov (413955)" to "Mashov (נעמי שמר פתח תקוה)"

## [0.1.28] - 2025-09-28

### Added
- Enhanced debugging logs for authentication token type checking
- Added detailed logging for accessToken structure analysis
- Improved error logging with full response data for troubleshooting

### Fixed
- Enhanced version file path resolution with alternative path fallback
- Added comprehensive debugging information for authentication flow

## [0.1.27] - 2025-09-28

### Fixed
- Fixed asyncio.create_task usage in config_flow that was causing authentication errors
- Enhanced version file debugging to help troubleshoot version logging issues
- Improved error handling in configuration flow

### Changed
- Simplified async task handling in config_flow for better compatibility
- Added more detailed debug logging for version file resolution

## [0.1.26] - 2025-09-28

### Fixed
- Fixed version file path resolution for proper version logging
- Added debug logging to help troubleshoot version file location

## [0.1.25] - 2025-09-28

### Fixed
- Fixed student ID usage - now using childGuid directly instead of converted hash
- Fixed version logging issue in integration setup
- Improved error handling for 404 and 400 HTTP responses
- Better handling of missing data endpoints

### Changed
- Student IDs now use the actual childGuid from Mashov API
- Enhanced error recovery for individual data fetch failures
- Improved logging for better debugging

## [0.1.24] - 2025-01-28

### Fixed
- Fixed students data extraction by using children data from authentication response
- Removed dependency on /api/me and /api/students endpoints that were returning errors
- Students are now extracted directly from login response children data
- Resolved 404/403 errors when fetching student information

### Added
- Better student data parsing from authentication response
- Enhanced logging for student extraction process
- Support for child GUID-based student identification

## [0.1.23] - 2025-01-28

### Fixed
- Fixed version logging path to correctly read VERSION file
- Changed students endpoint from /api/students to /api/me
- Resolved 403 "Internal error" when fetching student data
- Improved version detection for debugging purposes

### Added
- Better error handling for version file reading
- More robust path resolution for VERSION file

## [0.1.22] - 2025-01-28

### Fixed
- Fixed CSRF token handling for student data fetching
- Added proper X-Csrf-Token header extraction from login response
- Enhanced logging for CSRF token detection and usage
- Resolved "Failed to query students: HTTP 400: X-Csrf-Token" error

### Added
- CSRF token validation and logging
- Better error handling for missing CSRF tokens
- Enhanced debugging for authentication flow

## [0.1.21] - 2025-01-28

### Added
- Enhanced debug logging throughout authentication process
- Version information logging on integration startup
- Detailed step-by-step authentication flow logging
- Comprehensive error reporting with full response data
- Better visibility into login attempts and responses

### Changed
- Upgraded logging levels from DEBUG to INFO for critical authentication steps
- Enhanced error messages with more context and data
- Improved authentication flow visibility for troubleshooting

### Fixed
- Better debugging capabilities for authentication issues
- More detailed logging for failed login attempts

## [0.1.20] - 2025-01-28

### Fixed
- Fixed remaining "'dict' object has no attribute 'startswith'" error in authentication
- Removed problematic token string parsing that was causing authentication failures
- Simplified authentication flow to rely on accessToken/credential data presence
- Improved authentication success detection for Mashov API responses

### Changed
- Streamlined token handling logic to avoid string conversion errors
- Enhanced authentication flow to work with dict-based API responses

## [0.1.19] - 2025-01-28

### Fixed
- Fixed "'dict' object has no attribute 'startswith'" error in token parsing
- Improved token handling to support both string and dict token formats
- Fixed school names displaying "None" instead of proper city names
- Enhanced authentication flow to handle complex token responses from Mashov API
- Better error handling for different token formats and authentication responses

### Changed
- School names now display "לא צוין" instead of "None" when city is not available
- Improved token parsing logic to handle dict-based authentication responses
- Enhanced authentication data storage for better session management

## [0.1.18] - 2025-01-28

### Fixed
- Fixed "cannot access local variable 'asyncio'" error in config flow
- Added proper asyncio import at module level to prevent variable scope issues
- Resolved authentication flow crash during school selection process

## [0.1.17] - 2025-01-28

### Fixed
- Fixed "Cannot reach Mashov" authentication error
- Updated API version from 3.20210425 to 4.20250101 for compatibility with latest Mashov API
- Enhanced authentication token detection with multiple fallback methods
- Added comprehensive retry mechanism (3 attempts with 2-second delays) for login failures
- Improved error handling and logging throughout authentication process
- Enhanced session timeout settings (60 seconds total, 30 seconds connect)
- Better handling of network timeouts and connection issues
- Improved error messages in Hebrew translations for better user experience

### Changed
- Enhanced device identification parameters for better API compatibility
- Improved authorization header handling with multiple token formats
- Better session management with proper connection limits

## [0.1.16] - 2025-09-28

### Fixed
- Fixed SelectSelector value type error - values must be strings
- Corrected school selection dropdown data type handling
- Improved school choice processing with proper type conversion

## [0.1.15] - 2025-09-28

### Fixed
- Fixed integration failure during school search
- Removed premature authentication attempt during school name resolution
- Improved school search flow to only authenticate after school selection
- Enhanced error handling for school search operations

## [0.1.14] - 2025-09-28

### Fixed
- Fixed school selection display when multiple schools match
- Added proper school names with city and semel in selection dropdown
- Improved school choice presentation with SelectSelector
- Enhanced user experience for multiple school matches

## [0.1.13] - 2025-09-27

### Fixed
- Fixed Config Flow 400 Bad Request error by switching back to TextSelector
- Reduced school catalog from 200 to 50 items for better performance
- Improved autocomplete functionality with proper semel extraction
- Enhanced school selection user experience

## [0.1.12] - 2025-09-27

### Improved
- Properly implemented asyncio.create_task for all MainThread operations
- Fixed MainThread blocking in Config Flow, authentication, and data fetching
- Enhanced performance by running all network operations in background tasks
- Improved UI responsiveness during integration setup and data updates

## [0.1.11] - 2025-09-27

### Fixed
- Fixed Config Flow 400 Bad Request error
- Reverted to SelectSelector for better compatibility
- Fixed dropdown selection handling
- Improved school selection user experience

## [0.1.10] - 2025-09-27

### Fixed
- Fixed autocomplete error: 'NoneType' object has no attribute 'lower'
- Fixed session management - keep session open for future use
- Improved error handling for None values in school catalog
- Fixed "Unclosed client session" error during authentication
- Enhanced school catalog sorting with proper None handling

## [0.1.9] - 2025-09-27

### Improved
- Optimized MainThread usage to prevent UI blocking
- Added asyncio.create_task for parallel execution
- Improved performance by running operations in separate tasks
- Enhanced responsiveness during data fetching and school catalog loading

## [0.1.8] - 2025-09-27

### Fixed
- Fixed "Unclosed client session" error during authentication
- Improved session management with proper cleanup
- Added timeout handling for student data fetching
- Enhanced error handling for network issues
- Fixed session closure timing issues

## [0.1.7] - 2025-09-27

### Fixed
- Fixed ValueError in school selection dropdown
- Replaced SelectSelector with TextSelector for better autocomplete support
- Added proper semel extraction from autocomplete format
- Improved school selection user experience with working autocomplete
- Added debug logging for school ID selection process

## [0.1.6] - 2025-09-27

### Improved
- Enhanced school selection autocomplete performance
- Reduced school list from 500 to 200 items for better UI responsiveness
- Added sorting by school name for improved user experience
- Optimized dropdown performance with sort=True option
- Updated documentation with autocomplete improvements

### Fixed
- Improved autocomplete functionality in school selection dropdown
- Better handling of large school catalogs

## [0.1.5] - 2025-09-27

### Fixed
- Fixed Config Flow schema definition causing 400 Bad Request error
- Improved school selection dropdown handling with proper error handling
- Limited school catalog to 200 items for better autocomplete performance
- Added fallback to text input if dropdown creation fails
- Enhanced error logging for better troubleshooting of Config Flow issues
- Improved autocomplete functionality with sorted school list
- Optimized dropdown performance with sort=True option

## [0.1.4] - 2025-09-27

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.4] - 2025-09-27

### Added
- Comprehensive debug logging throughout the integration
- Enhanced error handling with detailed error messages
- Improved session management with proper cleanup
- Better timeout and connection error handling
- Custom icon.png and logo.png for better visuals in Home Assistant

### Changed
- Multiple students support - integration now fetches all children automatically
- School selection via dropdown with autocomplete (fallback to text input)
- Automatic school year detection (no manual year input needed)
- Enhanced authentication flow with better error reporting
- Updated translations for new UI flow (Hebrew and English)

### Fixed
- Fixed "Unclosed client session" errors during integration unload
- Improved authentication error messages
- Better handling of network timeouts and connection issues
- Fixed session cleanup on integration reload/restart
- Fixed syntax error in config flow schema

## [0.1.3] - 2025-09-27

### Added
- Comprehensive debug logging throughout the integration
- Enhanced error handling with detailed error messages
- Improved session management with proper cleanup
- Better timeout and connection error handling

### Changed
- Multiple students support - integration now fetches all children automatically
- School selection via dropdown with autocomplete (fallback to text input)
- Automatic school year detection (no manual year input needed)
- Enhanced authentication flow with better error reporting

### Fixed
- Fixed "Unclosed client session" errors during integration unload
- Improved authentication error messages
- Better handling of network timeouts and connection issues
- Fixed session cleanup on integration reload/restart

## [0.1.2] - 2025-09-27

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.1] - 2025-09-27

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1-beta.1] - 2025-09-27 (Pre-release)

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.0] - 2025-01-XX

### Added
- Initial release of Mashov integration for Home Assistant
- Support for authentication with Mashov API
- Four sensors: Timetable, Weekly Plan, Homework, Behavior
- Configurable homework days range (back/forward)
- Daily automatic refresh
- Manual refresh service
- Hebrew and English translations
- Options flow for configuration
- Diagnostics support

### Features
- Student selection support
- Automatic re-authentication on token expiry
- Comprehensive error handling
- Device information for each student
