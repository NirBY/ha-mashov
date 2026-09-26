# Mashov v1.0.13

Holiday devices and their sensor/calendar display names now include the school hub title, so holidays from different schools can be distinguished in Home Assistant.

- Apply the school label consistently to both holiday platforms, including existing installations after restart.
- Preserve device identifiers, entity IDs, unique IDs, history and user-defined names.
- Update through HACS and restart Home Assistant.

Validation: existing regression suite, Ruff, Python 3.13/3.14 CI, hassfest and HACS validation.
