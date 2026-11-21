# v1.5.0 — Absence and lateness counters

Issue #20 now has a dedicated **Absence and lateness counters (school year)** source under **Configure → Data to fetch**. It is read only and off by default.

- One sensor per student: state is total absence events, including justified and online absences. These are lesson events, not days absent.
- Attributes include lateness, justified/unjustified totals, and subject/teaching-group rows with original event names and counts.
- Counters cover September 1 through August 31 of the selected school year. Their dates are explicit and independent of the homework window.
- Classification uses each school's event definitions. Events without a standard Mashov category remain visible as unclassified; they are not silently included in absence/lateness totals.
- Temporary failures retain the previous counts and their original dates, marked stale. Permission or malformed-response failures do not become false zeroes. Raw student profiles are excluded from this source's cache and attributes.
- Assist/MCP exposes the same totals and dates alongside paginated rows, subject to the existing opt-in and administrator checks.

Both English and Hebrew READMEs and feature-tour GIFs now cover all **24 sources**. All five UI languages include the new option.

## Upgrade

Update through HACS or install `mashov.zip`, then restart Home Assistant. Enable **Absence and lateness counters (school year)** explicitly. Existing selections, schedules and entity IDs are preserved. The option also reads school event definitions and group labels; the separate Behavior and Study Groups sources do not need to be enabled.

## Validation

The implementation was verified with read-only live requests for three students across two schools. Date-filtered aggregates matched the underlying behavior-event counts. Regression checks cover school-specific codes, justifications, student isolation, schedules, stale data, bounded attributes and Assist/MCP metadata. The full release CI checks Python 3.13/3.14, Ruff, hassfest and HACS.

Issue #17 (follow-up note attachments) remains open because a real attachment schema and route still need verification.
