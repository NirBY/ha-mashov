"""Calendar-day search shared by dashboard templates and the bag blueprint.

The blueprint carries the same Jinja search because HA blueprints cannot import
Python helpers. Regression tests render both against the same calendar cases.
"""

SCHOOL_DAY_SEARCH = """
{%- set target = namespace(offset=1, found=false) -%}
{%- set school = namespace(days=[]) -%}
{%- for item in timetable_items if item.timeTable is defined -%}
  {%- set day = item.timeTable.day | int(-1) -%}
  {%- if 1 <= day <= 6 and day not in school.days -%}
    {%- set school.days = school.days + [day] -%}
  {%- endif -%}
{%- endfor -%}
{%- for offset in range(1, 367) if not target.found -%}
  {%- set candidate = now().date() + timedelta(days=offset) -%}
  {%- set day = (candidate.isoweekday() % 7) + 1 -%}
  {%- set holiday = namespace(blocked=false) -%}
  {%- for item in holiday_items if item.start is defined -%}
    {%- set start = as_datetime(item.start, none) -%}
    {%- set end = as_datetime(item.end, none) if item.end is defined and item.end else start -%}
    {%- if start and start.date() <= candidate <= (end or start).date() -%}
      {%- set holiday.blocked = true -%}
    {%- endif -%}
  {%- endfor -%}
  {%- if day != 7 and (not school.days or day in school.days) and not holiday.blocked -%}
    {%- set target.offset = offset -%}
    {%- set target.found = true -%}
  {%- endif -%}
{%- endfor -%}
"""
