[← README](../README.md) · [Dashboard guide](dashboard.md) · [Automation blueprints](blueprints.md)

# Services

## `mashov.refresh_now`
Trigger an immediate refresh.
```yaml
service: mashov.refresh_now
data:
  entry_id: YOUR_ENTRY_ID  # optional; if omitted, all entries refresh
```

Calling without `entry_id` refreshes all configured Mashov hubs.

## `mashov.set_options`

Update a hub's options without opening Configure:

```yaml
service: mashov.set_options
data:
  entry_id: YOUR_ENTRY_ID
  schedule_type: weekly
  schedule_time: "14:00"
  schedule_days: [0, 2, 4]  # Monday, Wednesday, Friday
```

To change the data selection, provide the complete list of categories to keep enabled:

```yaml
action: mashov.set_options
data:
  entry_id: YOUR_ENTRY_ID
  enabled_data: [homework, timetable, message_board, periodic_grades]
```

Legacy `additional_data` changes only optional student sources and preserves core data and Mailbox.

For backward compatibility, omitting `entry_id` targets the first loaded hub.
Specify it when selecting a particular hub. The legacy `schedule_day` field remains
supported; supplying it without `schedule_days` replaces the selected days with
that one day. Invalid service inputs are rejected. YAML scheduling overrides still apply.

### Per-data and per-student schedules

Set homework to refresh every 30 minutes and grades weekly on Friday. Other selected types follow the shared schedule:

```yaml
action: mashov.set_options
data:
  entry_id: YOUR_ENTRY_ID
  data_schedules:
    homework:
      schedule_type: interval
      schedule_interval: 30
    grades:
      schedule_type: weekly
      schedule_time: "18:00"
      schedule_days: [4]
```

`data_schedules` replaces the complete account override map; `{}` restores shared inheritance. To configure an individual student, use the stable student ID and `student_schedules`:

```yaml
action: mashov.set_options
data:
  entry_id: YOUR_ENTRY_ID
  student_schedules:
    YOUR_STUDENT_ID:
      general:
        schedule_type: daily
        schedule_time: "16:00"
      overrides:
        homework:
          schedule_type: interval
          schedule_interval: 45
```

This replaces the student schedule map, so include all students/overrides you want to retain. Holidays and Mailbox are account/school resources and cannot be student overrides. Disabled sources are never fetched. Short intervals increase portal requests and may produce more login/activity emails.

## `mashov.create_live_dashboard`

Build the Mashov Live dashboard into an existing UI dashboard. With no `students` list it includes every child from every hub. The [dashboard script blueprint](dashboard.md) calls this service; you can also call it directly:

```yaml
action: mashov.create_live_dashboard
data:
  dashboard: mashov-live          # URL of an existing, empty UI dashboard
  title: משוב לייב
  family: [person.parent_1, person.parent_2]
  overwrite: false                # true replaces other content or a built-in dashboard
  students:                       # optional tweaks; omitted children still appear
    - name: נועה                  # full name, or a unique first name
      emoji: "🚀"
      person: person.noa          # photo + this user sees the card
      viewers: [person.grandma]   # optional extra viewers
      accent: [155, 176, 201]     # RGB list or "#9bb0c9"
response_variable: result
```

The response reports the dashboard, the number of students and whether the Bubble Card resource was found. There is no limit on the number of children.

---
