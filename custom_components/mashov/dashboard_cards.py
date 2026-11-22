"""Readable RTL student details using native cards and optional card-mod accents."""

import json


def card_style(accent):
    """A steady glow on the border, with high-contrast text and responsive tables."""
    return {
        "style": {
            ".": f"""
                ha-card {{
                  background: linear-gradient(145deg, #141e32, #0c1424);
                  color: #f1f5ff; border: 1px solid {accent}55;
                  border-radius: 22px; overflow: hidden;
                  box-shadow: 0 0 18px {accent}16, inset 0 1px 0 {accent}33;
                  --primary-text-color: #f1f5ff; --secondary-text-color: #becde0;
                  --ha-card-header-color: #f1f5ff;
                }}
            """,
            "ha-markdown$": f"""
                ha-markdown-element {{ direction: rtl; line-height: 1.65; font-size: 15px; }}
                h2, h3 {{ color: {accent}; margin: 2px 0 12px; font-weight: 700; }}
                table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
                th, td {{ text-align: start !important; padding: 9px 5px !important;
                  border-bottom: 1px solid #ffffff12; overflow-wrap: anywhere; }}
                th {{ color: #bdcde0; font-size: 12px; font-weight: 500; }}
                table[role=presentation] td {{ text-align: center !important; border: 0; width: 33%; }}
                table[role=presentation] h2 {{ font-size: 30px; margin: 0; line-height: 1.2; }}
                small {{ color: #bdcde0; }}
                summary {{ color: {accent}; cursor: pointer; padding: 12px 0; min-height: 24px; }}
                details {{ border-top: 1px solid #ffffff14; margin-top: 12px; }}
                a {{ color: {accent}; }}
                @media (max-width: 420px) {{
                  ha-markdown-element {{ font-size: 14px; }}
                  th, td {{ font-size: 12px; padding: 8px 3px !important; }}
                }}
            """,
        }
    }


def markdown_card(content, accent):
    return {"type": "markdown", "content": '<div dir="rtl">\n\n' + content + "\n</div>", "card_mod": card_style(accent)}


def cell(expression):
    """Plain portal text in a table: no HTML, Markdown links, pipes or line breaks."""
    return (
        "{{ ((" + expression + ") or '') | string | striptags | e | replace('\\n', ' ') "
        "| replace('\\r', '') | replace('|', '&#124;') | replace('[', '&#91;') | replace(']', '&#93;') }}"
    )


def freshness(entity):
    e = json.dumps(entity)
    return (
        f"{{% if state_attr({e}, 'data_stale') %}}"
        '<ha-alert alert-type="warning">מוצג המידע האחרון שנשמר. הרענון טרם הושלם.</ha-alert>\n'
        "{% endif %}"
        f"{{% set updated = state_attr({e}, 'last_update') %}}"
        "{% if updated %}<small>עודכן {{ as_timestamp(updated, 0) | timestamp_custom('%d/%m · %H:%M') }}</small>\n{% endif %}"
    )


def guard(entity, content, empty="הנתונים אינם זמינים כרגע. נסו לרענן מאוחר יותר."):
    e = json.dumps(entity)
    return (
        f"{{% if has_value({e}) %}}"
        + freshness(entity)
        + "\n"
        + content
        + '{% else %}<ha-alert alert-type="info">'
        + empty
        + "</ha-alert>{% endif %}"
    )


def attendance_card(entity, accent):
    e = json.dumps(entity)
    body = (
        '<table role="presentation"><tr>'
        f"<td><h2>{{{{ states({e}) }}}}</h2>היעדרויות</td>"
        f'<td><h2>{{{{ state_attr({e}, "lateness") }}}}</h2>איחורים</td>'
        f'<td><h2>{{{{ state_attr({e}, "lessons_count") }}}}</h2>שיעורים</td>'
        "</tr></table>\n\n"
        f"{{{{ state_attr({e}, 'justified_absences') }}}} היעדרויות מוצדקות · "
        f"{{{{ state_attr({e}, 'unjustified_absences') }}}} ללא הצדקה\n\n"
        f"{{{{ state_attr({e}, 'justified_lateness') }}}} איחורים מוצדקים · "
        f"{{{{ state_attr({e}, 'unjustified_lateness') }}}} ללא הצדקה\n\n"
        f"<small>אירועים בשיעורים, לא ימי היעדרות · שנת לימודים {{{{ state_attr({e}, 'school_year') }}}}<br>"
        f"מ־<bdi>{{{{ state_attr({e}, 'period_start') }}}}</bdi> "
        f"עד <bdi>{{{{ state_attr({e}, 'period_end') }}}}</bdi></small>\n\n"
        f"{{% if state_attr({e}, 'unclassified_events') %}}"
        f"<ha-alert alert-type=\"info\">יש {{{{ state_attr({e}, 'unclassified_events') }}}} אירועים נוספים ללא סיווג תקני. "
        "הם מוצגים בנפרד ואינם נכללים במוני ההיעדרויות והאיחורים.</ha-alert>{% endif %}\n\n"
        "<details><summary>פירוט לפי מקצוע</summary>\n\n"
        "| מקצוע | היעדרויות | איחורים | נוספים |\n|---|:-:|:-:|:-:|\n"
        f"{{% for x in state_attr({e}, 'items') or [] %}}| "
        + cell("x.subject or x.group_name or 'מקצוע לא ידוע'")
        + " | {{ x.absences }} | {{ x.lateness }} | {{ x.other_events + x.unclassified_events }} |\n{% endfor %}\n"
        f"{{% if (state_attr({e}, 'stored_items') or 0) < (state_attr({e}, 'total_items') or 0) %}}"
        "<small>הפירוט חלקי בגלל מגבלת גודל. הסכומים בראש הכרטיס כוללים את כל האירועים.</small>{% endif %}\n\n</details>"
    )
    return markdown_card("### ◈ נוכחות לאורך השנה\n\n" + guard(entity, body), accent)


def subjects_card(groups, lessons, accent):
    g, lessons_id = json.dumps(groups), json.dumps(lessons)
    count_source = (
        f"{{% set counts = (state_attr({lessons_id}, 'items') or []) if has_value({lessons_id}) else [] %}}"
        if lessons
        else "{% set counts = [] %}"
    )
    body = (
        f"{{% set groups = state_attr({g}, 'items') or [] %}}"
        + count_source
        + "{% if groups %}**{{ groups | count }} קבוצות לימוד** · מקצועות, מורים ושעות שבועיות\n\n"
        "<details><summary>המקצועות והמורים שלי</summary>\n\n"
        "| מקצוע ומורה | שבועי | התקיימו |\n|---|:-:|:-:|\n"
        "{% for g in groups %}{% set count = (counts | selectattr('groupId', 'eq', g.groupId) | list | first) | default({}) %}| "
        + cell("g.subjectName or g.groupName")
        + "<br><small>"
        + cell("(g.groupTeachers or []) | map(attribute='teacherName') | join(', ')")
        + "</small> | {{ count.weeklyHours | default('—') }} | {{ count.lessonsCount | default('—') }} |\n{% endfor %}\n"
        "</details>{% else %}בית הספר לא פרסם קבוצות לימוד.{% endif %}\n"
    )
    if lessons:
        body += (
            f"{{% if not has_value({lessons_id}) %}}<small>מוני השיעורים אינם זמינים כרגע.</small>"
            f"{{% elif state_attr({lessons_id}, 'data_stale') %}}<small>מוני השיעורים ממתינים לרענון.</small>{{% endif %}}"
        )
    return markdown_card("### ◇ המקצועות שלי\n\n" + guard(groups, body), accent)


def lessons_card(entity, accent):
    """A useful fallback when group labels were not selected."""
    e = json.dumps(entity)
    content = (
        "<details><summary>שיעורים לפי קבוצת לימוד</summary>\n\n"
        "| קבוצה | שעות שבועיות | שיעורים שהתקיימו |\n|---|:-:|:-:|\n"
        f"{{% for x in state_attr({e}, 'items') or [] %}}"
        "| {{ x.groupId }} | {{ x.weeklyHours }} | {{ x.lessonsCount }} |\n{% endfor %}\n</details>"
    )
    return markdown_card("### ◇ מוני שיעורים\n\n" + guard(entity, content), accent)


def bells_card(entity, accent):
    e = json.dumps(entity)
    content = (
        f"{{% set bells = state_attr({e}, 'items') or [] %}}"
        "{% if bells %}<details><summary>צלצולים · {{ bells | count }} שיעורים ביום</summary>\n\n"
        "| שיעור | התחלה | סיום |\n|:-:|:-:|:-:|\n"
        "{% for x in bells %}| {{ x.lessonNumber | default('—') }} | "
        + cell("(x.startTime | default('—'))[:5]")
        + " | "
        + cell("(x.endTime | default('—'))[:5]")
        + " |\n{% endfor %}\n</details>"
        "{% else %}בית הספר לא פרסם זמני צלצולים.{% endif %}"
    )
    return markdown_card("### ◷ שעות הלימודים\n\n" + guard(entity, content), accent)


def extra_student_cards(student):
    cards = []
    accent = student["accent"]
    if student.get("attendance_counts"):
        cards.append(attendance_card(student["attendance_counts"], accent))
    if student.get("study_groups"):
        cards.append(subjects_card(student["study_groups"], student.get("lessons_count"), accent))
    elif student.get("lessons_count"):
        cards.append(lessons_card(student["lessons_count"], accent))
    if student.get("timetable"):
        cards.append(
            {
                "type": "custom:mashov-weekly-card",
                "entity": student["timetable"],
                "bells_entity": student.get("bells"),
                "holidays_entity": student.get("holidays"),
                "accent": accent,
            }
        )
    elif student.get("bells"):
        cards.append(bells_card(student["bells"], accent))
    return cards
