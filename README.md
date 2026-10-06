# Mashov – Home Assistant Integration (HACS)

Unofficial integration for **משו"ב (Mashov)**. Choose which school data Home Assistant fetches, per account and school hub.

Current release: **v1.0.17**. Requires **Home Assistant 2025.3 or newer**.
See [release notes](RELEASE_NOTES.md) for fixes and upgrade compatibility.

> This project is **community-made** and not affiliated with Mashov.

## בחירת המידע — מה זמין ומה מופעל כברירת מחדל

**בהתקנה חדשה כל 18 הקטגוריות כבויות.** בוחרים ידנית רק את המידע הדרוש, בהגדרה הראשונית או בהגדרות האינטגרציה בהמשך. בחירת הקטגוריות חלה על כל התלמידים באותו חשבון ובאותו מוסד. חופשות הן ברמת המוסד ותיבת הדואר היא ברמת החשבון.

**בעדכון נשמרת הבחירה הקודמת.** במעבר מגרסאות 1.0.7–1.0.15, שבע קטגוריות הבסיס שהיו פעילות ממשיכות לפעול, ונשמרים גם סוגי המידע הנוספים שבחרתם. מי שהוסיף חשבון ב־1.0.15 עם לוח מודעות פעיל ממשיך לקבל אותו. החל מ־1.0.16 נשמרת גם בחירה ריקה או חלקית. עדכון אינו מפעיל תיבת דואר, תוכן מלא או שעות פרטניות. מזהי הישויות, השמות וההתאמות האישיות נשמרים; ישות שהמשתמש השבית ידנית נשארת מושבתת.

| קטגוריה / שם באנגלית | מה מתקבל | חשבון חדש | שדרוג מ־1.0.7–1.0.15 |
| ---: | ---: | ---: | ---: |
| שיעורי בית / Homework | מטלות בחלון התאריכים שנבחר (`homework`) | כבוי — בחירה ידנית | בסיס — נשאר פעיל |
| התנהגות / Behavior | אירועי התנהגות בחלון התאריכים (`behavior`) | כבוי — בחירה ידנית | בסיס — נשאר פעיל |
| תכנון שבועי / Weekly plan | תכנון שיעורים שפורסם (`weekly_plan`) | כבוי — בחירה ידנית | בסיס — נשאר פעיל |
| מערכת שעות / Timetable | מערכת שבועית (`timetable`) | כבוי — בחירה ידנית | בסיס — נשאר פעיל |
| היסטוריית שיעורים / Lesson history | יומן שיעורים שהשרת מחזיר (`lessons_history`) | כבוי — בחירה ידנית | בסיס — נשאר פעיל |
| ציונים / Grades | רשימת ציונים (`grades`) | כבוי — בחירה ידנית | בסיס — נשאר פעיל |
| חופשות / Holidays | חיישן חופשות וישות לוח שנה (`holidays`) | כבוי — בחירה ידנית | בסיס — נשאר פעיל |
| לוח מודעות / Noticeboard | הודעות כלליות מבית הספר ותאריכי תפוגה (`message_board`) | כבוי — בחירה ידנית | נשמרת הבחירה הקודמת, כולל ברירת המחדל של חשבון שנוצר ב־1.0.15 |
| התנהגות יומית / Daily behavior | רשומות יומיות בחלון התאריכים (`daily_behavior`) | כבוי — בחירה ידנית | נשמרת הבחירה הקודמת |
| התנהגות מחוץ לשיעור / Outside lesson behavior | אירועים מחוץ לשיעורים בחלון התאריכים (`outside_behavior`) | כבוי — בחירה ידנית | נשמרת הבחירה הקודמת |
| הערות מעקב / Follow-up notes | הערות צוות בחלון התאריכים (`follow_up`) | כבוי — בחירה ידנית | נשמרת הבחירה הקודמת |
| ציונים תקופתיים / Term grades | ציונים לפי תקופה (`periodic_grades`) | כבוי — בחירה ידנית | נשמרת הבחירה הקודמת |
| תעודות / Report cards | רשומות תעודות; ללא הורדת קבצים (`report_cards`) | כבוי — בחירה ידנית | נשמרת הבחירה הקודמת |
| חומרי לימוד / Study materials | רשומות חומרי לימוד; ללא הורדת קבצים (`study_materials`) | כבוי — בחירה ידנית | נשמרת הבחירה הקודמת |
| קובצי תלמיד / Student files | רשומות קבצים; ללא הורדת הקבצים עצמם (`student_files`) | כבוי — בחירה ידנית | נשמרת הבחירה הקודמת |
| בקשות להצדקת היעדרות / Absence justification requests | בקשות קיימות בחלון התאריכים; לא מגיש בקשות (`justification_requests`) | כבוי — בחירה ידנית | נשמרת הבחירה הקודמת |
| שעות פרטניות / Individual lessons | רשומות שיעורים פרטניים שהמוסד מפרסם (`special_hours`) | כבוי — בחירה ידנית | כבוי — נוסף ב־1.0.16 |
| תיבת דואר / Mailbox — headers and unread count | מספר שיחות שלא נקראו וכותרות השיחות האחרונות, ללא סימון כנקראו (`mailbox`) | כבוי — בחירה ידנית | כבוי — נוסף ב־1.0.16 |
| ↳ תוכן מלא של הודעות / Full message content | תוספת לתיבת הדואר: גוף ההודעות כטקסט בלבד, ללא קבצים מצורפים. ![אזהרה: שליפת תוכן מלא מסמנת באתר משו״ב את השיחות שנשלפו כנקראו, גם אם לא פתחתם אותן בעצמכם. Full-content retrieval marks conversations read.](docs/images/mailbox-read-warning.svg) | כבוי — דורש סימון נפרד | כבוי — דורש הסכמה מפורשת |

זמינות המידע תלויה בהרשאות המוסד. חוסר הרשאה מוצג כ־`unknown` עם `source_status: forbidden` או `unsupported`; מקור תקין ללא רשומות מציג `0`. לוח המודעות נפרד מתיבת הדואר. שאלונים, אישורי הורים, שליחת הודעות, טיוטות, ארכיון וקבצים מצורפים אינם נתמכים כרגע.

### איך בוחרים בהתקנה ראשונית

1. לאחר התקנה דרך HACS והפעלה מחדש: **הגדרות → מכשירים ושירותים → הוספת אינטגרציה → Mashov** (בממשק אנגלי: **Settings → Devices & services → Add integration → Mashov**).
2. הזינו משתמש, סיסמה ומוסד. בשדה **סוגי מידע לשליפה / Data to fetch** פתחו את הרשימה ובחרו קטגוריה. חזרו על הפעולה לכל קטגוריה נוספת. קטגוריה שנבחרה מופיעה כתגית; לחיצה על **×** מסירה אותה. הרשימה מציגה רק קטגוריות שעדיין לא נבחרו.
3. לתיבת דואר בחרו **Mailbox — headers and unread count**. רק אם דרוש גוף ההודעות, סמנו בנפרד **שליפת תוכן מלא של הודעות / Full message content (marks conversations read)**, לאחר קריאת האזהרה. מספר השיחות האחרונות הוא **20 כברירת מחדל**, בטווח **1–50**.
4. לחצו **שליחה / Submit**. אין צורך להוסיף חיישנים ידנית: נוצרות ישויות לסוגים שנבחרו. שמירה בלי בחירה לא יוצרת חיישני מידע; החשבון עדיין מתחבר ומזהה את התלמידים.

![מסך הגדרה ראשונית אמיתי ב־Home Assistant: בחירת מידע ריקה ותוכן מלא כבוי](docs/images/initial-data-selection.jpg)

### איך משנים חשבון קיים לאחר עדכון

1. עדכנו דרך HACS והפעילו מחדש את Home Assistant.
2. פתחו **הגדרות → מכשירים ושירותים → Mashov**, ולחצו על גלגל השיניים **הגדרה / Configure** ליד המוסד הרצוי. אין צורך למחוק ולהוסיף מחדש את האינטגרציה.
3. התגיות מציגות את הבחירה הקיימת. הוסיפו דרך **סוגי מידע לשליפה / Data to fetch** והסירו באמצעות **×**. בחשבונות מרובים מגדירים כל חשבון בנפרד.
4. לחצו **שליחה / Submit**. שינוי קטגוריות, תוכן מלא או מגבלת השיחות טוען מחדש את החשבון ומנסה לרענן מיד. לאחר מכן פועל לוח הרענון הקיים — ברירת המחדל היא כל יום ב־14:00. בקשת מידע שמוסד חסם עשויה להמתין לתום ההשהיה של אותו מקור.

![מסך אפשרויות אמיתי: הבחירות הקיימות נשמרות ותוכן מלא נשאר כבוי](docs/images/existing-data-selection.jpg)

הצילומים מציגים את השדות בממשק האנגלי של Home Assistant. צולמו מתוך הטפסים עצמם, ללא פרטי כניסה או שמות תלמידים; פתיחת הטופס לצילום אינה משנה את ההגדרות.

### מה קורה בכיבוי וכמה זמן המידע נשמר

| פעולה / מקום שמירה | מה קורה בפועל |
| ---: | ---: |
| הסרת קטגוריה ולחיצה על Submit | לאחר טעינה מחדש נעצרות הבקשות למקור הזה. נתוניו מוסרים מהמטמון הפעיל ומהקובץ המקומי **לפני ניסיון התחברות**, גם אם משו״ב אינו זמין. הישויות מושבתות אך מזהיהן ושמותיהן נשמרים להפעלה חוזרת. כרטיס ידני שמפנה אליהן עשוי להציג „לא זמין”. |
| כיבוי תוכן מלא בלבד | גופי ההודעות נמחקים מהמטמון הפעיל ומהקובץ המקומי; כותרות וספירת שיחות ממשיכות להתעדכן אם תיבת הדואר נבחרה. הודעות שכבר סומנו באתר כנקראו אינן חוזרות למצב „לא נקרא”. |
| הסרת תיבת הדואר | מוסרת גם את הכותרות מהמטמון ומאפסת את סימון התוכן המלא. הוספת תיבת הדואר מחדש מתחילה בכותרות בלבד. |
| השבתת ישות ידנית במסך Entities | אינה משנה את בחירת הקטגוריה ואינה עוצרת את שליפתה עבור החשבון. להפסקת שליפה יש להסיר את הקטגוריה מתוך Configure. |
| השבתת כל חשבון האינטגרציה דרך התפריט | עוצרת את הפעילות, אך משאירה את המטמון וההזדהות להפעלה חוזרת. להסרת הנתונים מהמטמון יש לבטל קטגוריות ולשמור לפני ההשבתה, או למחוק את חשבון האינטגרציה. |
| בחירה ריקה | אין בקשות לקטגוריות המידע. רשימת התלמידים וההזדהות נשמרות לצורך החשבון; זו אינה מחיקה של החשבון. |
| המטמון של האינטגרציה | נשמרת תמונת המצב האחרונה, **ללא מספר ימים קבוע וללא מחיקה לפי גיל**. רענון מוצלח מחליף אותה; כשל יכול להשאיר נתונים קודמים ללא הגבלת זמן עם סימון מידע לא עדכני. כיבוי קטגוריה מסיר אותה מהמטמון בטעינה מחדש. מחיקת חשבון האינטגרציה מוחקת את קובץ המטמון וההזדהות שלו. |
| כותרות ותוכן תיבת הדואר | עד מספר השיחות שנבחר, כברירת מחדל 20; זו מגבלת כמות ולא זמן. הקטנת המספר מצמצמת גם את המטמון בטעינה מחדש. אין תאריך תפוגה נפרד לתוכן שנשאר במטמון. |
| חלון תאריכים | שיעורי בית, התנהגות והמקורות שמסומנים בטבלה ככאלה משתמשים כברירת מחדל ב־7 ימים אחורה ו־21 קדימה. זהו חלון בקשה מהשרת, **לא מחיקת היסטוריה**. יתר המקורות תלויים במה שמשו״ב מחזיר לשנת הלימודים. |
| היסטוריית Home Assistant | נשמרת בנפרד לפי Recorder. ברירת המחדל של HA היא **10 ימים** וניקוי אוטומטי מדי לילה; הגדרה אישית יכולה להיות ארוכה יותר או לבטל ניקוי. ימי ההיסטוריה נספרים מזמן רישום מצב החיישן, לא מתאריך ההודעה; הודעה ישנה שנשלפת שוב עשויה להירשם שוב. ביטול קטגוריה או מחיקת חשבון אינם מוחקים היסטוריה שכבר נרשמה, כולל טקסט הודעות במאפייני החיישן. ראו [תיעוד Recorder](https://www.home-assistant.io/integrations/recorder/). |
| גיבויים, ייצוא ואוטומציות | עותקים בגיבויי HA/NAS, בקבצים או בהודעות שאוטומציה שלחה נשמרים לפי המדיניות שלהם. כיבוי באינטגרציה אינו מוחק אותם. המידע באתר משו״ב עצמו אינו נמחק. |

להפסקת רישום **עתידי** של תוכן הודעות להיסטוריה ניתן להחריג את מזהה חיישן תיבת הדואר תחת `recorder.exclude.entities` ב־`configuration.yaml` ולהפעיל מחדש. ההחרגה אינה מוחקת היסטוריה קיימת ואינה מבטלת את המטמון הנוכחי. אין לבצע מחיקת היסטוריה או שינוי מדיניות גיבוי כחלק מעדכון רגיל של האינטגרציה.

**English quick reference:** All 18 datasets start off for new hubs; existing hubs keep their previous choices. Open **Configure → Data to fetch**, add categories from the list or remove selected chips with **×**, then **Submit**. Mailbox headers do not mark messages read; the separate default-off full-content checkbox does. Opt-outs scrub the integration cache before login, including when a refresh fails. Cache snapshots have no age-based expiry; Recorder history and backups follow their own retention policies.

---

## 🧩 Features
- Simple **Config Flow (UI)** via Settings → Devices & Services → Add Integration → **Mashov**.
- **Daily refresh** (14:00 by default) + `mashov.refresh_now` service for on-demand updates.
- **Sensors** expose compact **state** (count) + rich **attributes** (lists you can use in automations / dashboards).
- **Calendar entity** for school holidays - integrates with Home Assistant calendar view 📅
- **Diagnostics** endpoint for safe issue reporting (redacts credentials).
- **Mashov Live dashboard** (Bubble Card) built by a script blueprint, with person photos and per-person card visibility.
- **Choose each data source** per school hub, including homework, timetable, grades, holidays and additional student data. New hubs start with no datasets selected; existing hubs keep their choices.
- **Mailbox**: opt-in unread count and recent inbox headers, with a separate, default-off full-content option that marks fetched conversations read in Mashov.
- **Noticeboard notices**: optional sensor plus a blueprint that notifies and reads new notices aloud, with built-in quiet hours.

---

## 📦 Installation

### Via HACS (recommended)
1. Open **HACS → Integrations → ⋯ → Custom repositories**.
2. Add repository URL: `https://github.com/NirBY/ha-mashov`. Select **Category: Integration**.
3. Search for **Mashov** in HACS, install, and **Restart Home Assistant**.

### Manual
1. Copy `custom_components/mashov` into your HA `/config/` folder.
2. Restart Home Assistant.

> The integration includes a custom `icon.png`.

---

## ⚙️ Configuration

1. **Add Integration → Mashov**.
2. Enter **username / password**.
3. Pick your **school** from the dropdown with **fast autocomplete** (type to filter). If the list doesn't load, a text field appears; type the **school name in Hebrew** or the **Semel** and we'll resolve it.
4. Select the required categories in **Data to fetch** (initially empty), then **Submit**. Only selected sensors/calendar are created. Mailbox full content requires a separate opt-in and marks fetched conversations read.

### Options

To configure options, go to: **Settings → Devices & Services → Mashov → Configure**

Credential updates in **Configure** apply only to the specific Mashov hub entry you opened. If you have multiple Mashov hubs, updating one hub's username or password does **not** automatically update the others.

Duplicate accounts for the same school are detected during setup. Different accounts
can expose the same child in separate hubs without sensor unique-ID collisions.
The school year advances automatically on September 1 unless an existing entry has
an explicitly configured year; that year remains pinned until you enable
**Automatic school year** in Configure (or `automatic_school_year: true` with `mashov.set_options`).

- **Homework window**: days back (default 7), days forward (default 21)
- **Daily refresh time**: default `14:00`
- **API base**: default `https://web.mashov.info/api/` (override if your deployment differs)
- **Max items in attributes**: maximum items to store in sensor attributes (default 100, range: 10-500)
  - Controls how many recent items are stored in sensor attributes to prevent database size issues
  - Sensors automatically clean technical fields and limit size to fit within Home Assistant's 16KB limit
  - Full data is always available via `coordinator.data` for advanced automations
  - Attributes show `total_items` (all available) and `stored_items` (actually stored in attributes)

#### Important note about night-time polling
- Pulling data at night may trigger email notifications from Mashov about account activity/logins. If this is undesirable:
  - Prefer scheduling the daily/weekly refresh to daytime hours (e.g., `14:00`).
  - Use the Options screen or YAML to set `schedule_type` and `schedule_time` accordingly.
  - Avoid long-running `interval` mode during overnight hours.

### Additional student data (optional)

Every dataset is now selectable, including the six main sensors (homework, behavior,
weekly plan, timetable, lessons history, grades), holidays and ten additional student
resources below. Deselecting a type stops its requests, removes its active/disk cache before login on reload, and disables its entities.
New installations select only what they need. Existing installations retain their
previous core data and optional selections; no mailbox or newly added source is enabled
by upgrading. Disabled entities retain their entity IDs, user customizations and history
and can be enabled again. Entities disabled manually in Home Assistant remain disabled.

**What changed, and since which version**

| Version | Change |
| --- | --- |
| v1.0.7 | The nine additional data types became available. Turn them on per school hub, as described below. |
| v1.0.15 | Hubs created in this version started with **Noticeboard** turned on; that choice is preserved when upgrading. |
| v1.0.15 | New blueprint that notifies you about new noticeboard notices and reads them aloud (see [below](#-automation-blueprint-new-noticeboard-notice)). |
| v1.0.16 | All datasets are selectable. Existing hubs, including those configured since v1.0.7, retain their selections and entity IDs. New setups start with an empty selection. Adds mailbox and individual lessons. |

**How to turn them on**

1. Go to **Settings → Devices & services → Mashov**.
2. Next to the school hub, click **Configure** (with several hubs, do this for each one).
3. In **Data to fetch** (Hebrew UI: **סוגי מידע לשליפה**), select what you want to keep enabled.
4. Click **Submit**. A changed selection reloads the hub and fetches the selected data immediately.
   An empty selection stops dataset polling; credentials and student discovery remain part of account setup.

From an automation or script you can do the same with the `mashov.set_options` action:

```yaml
action: mashov.set_options
data:
  entry_id: <your hub's entry id>   # optional with a single hub
  enabled_data: [homework, timetable, message_board, periodic_grades]
```

The list replaces the entire selection, so include everything you want to keep.
Older automations using `additional_data` still work: that key changes only the optional
student sources and preserves the selected core data and mailbox.

**What each one gives you** (one sensor per child; the state is the number of items)

| Option (English / Hebrew) | Key | Contents |
| --- | --- | --- |
| Noticeboard / לוח מודעות | `message_board` | Notices the school posts for parents: text (`eventtext`, HTML), ID (`eventid`), expiration date |
| Daily behavior / התנהגות יומית | `daily_behavior` | Daily behavior records within the homework date window |
| Outside lesson behavior / התנהגות מחוץ לשיעור | `outside_behavior` | Behavior events outside lessons (breaks, trips), within the date window |
| Follow-up notes / הערות מעקב | `follow_up` | Staff follow-up notes, within the date window |
| Term grades / ציונים תקופתיים | `periodic_grades` | Term (period) grades |
| Report cards / תעודות | `report_cards` | Report card records (metadata only) |
| Study materials / חומרי לימוד | `study_materials` | Study material records (metadata only, files are not downloaded) |
| Student files / קובצי תלמיד | `student_files` | Student file records (metadata only, files are not downloaded) |
| Absence justification requests / בקשות להצדקת היעדרות | `justification_requests` | Absence justification requests, within the date window |
| Individual lessons / שעות פרטניות | `special_hours` | Individual-lesson records (`specialHoursLessons`), when published by the school |

The "date window" is the homework days-back/days-forward setting. Find the new sensors in
**Developer Tools → States** by searching for the option name; the records are in the `items` attribute.

**Good to know**
- These student resources do not submit forms or download files. The separate mailbox full-content option
  below has read-status side effects and requires explicit opt-in.
- Each school decides what parents can see. A type your school does not allow shows state `unknown` with
  `source_status: forbidden` (or `unsupported`). It is checked again after 24 hours, separately for each child.
  An allowed type with no records shows `0`.
- Attributes are limited in size. When records are left out, `stored_items` is smaller than `total_items`.
- Parent approvals and the Shahaf exam calendar are not integrated. A read-only online-form list is also
  exposed by the portal (`user/forms?isParentsConsent=false`); its route was verified on 2026-10-06 but the
  tested account had no records, so form content/answer status has not been validated or added.

### Mailbox (optional)

Select **Mailbox — headers and unread count** to create one sensor per account/school hub,
not one per child. Its state is the current number of unread conversations. Attributes
contain the inbox count and the latest **20 conversations** (configurable from 1 to 50),
with conversation/message IDs, subject, sender, date, read status and attachment indicator.
Header-only mode does not open conversations or mark them read.

**Full message content is off by default. Enabling it marks fetched conversations as read
in Mashov, even if you have not opened them yourself.** This behavior was confirmed against
the live portal: the conversation GET alone changed the unread count from 1 to 0.
Only the fetched recent inbox conversations are opened; older inbox pages, sent mail,
drafts and archived conversations are not fetched. Turning off Mailbox also resets
full-content consent; selecting it again starts in header-only mode.

Bodies are exposed as plain text in `items[].messages[].body`; HTML is not executed and
images/attachments are never downloaded. Attributes stay below Home Assistant's recorder
budget. Long bodies can be shortened in sensor attributes (`body_truncated: true` and
`content_truncated: true`); the coordinator retains the fetched full text. Check
`stored_conversations` versus `fetched_conversations` for omitted records. Per-conversation
`content_status` shows failed body fetches, and `counts_status` shows unread-count failures;
failures are never presented as zero unread. The unread count is refreshed after body fetching.

```yaml
action: mashov.set_options
data:
  entry_id: <your hub's entry id>
  enabled_data: [homework, timetable, mailbox]
  mailbox_full_content: false
  mailbox_limit: 20
```

Message content stays in your Home Assistant instance/cache and may be recorded in sensor
history. Diagnostics contain technical statuses only, never message bodies, subjects, senders
or conversation IDs. Selection changes do not delete existing Recorder history.

### Configuration via configuration.yaml (optional)
You can also configure the refresh schedule via YAML. Scheduling values in YAML
override the Options UI. Configure the API base, homework window, and item limit
through the Options UI.

```yaml
mashov:
  # Scheduling
  schedule_type: daily        # daily | weekly | interval
  schedule_time: "14:00"      # for daily/weekly
  schedule_day: 0             # 0=Monday ... 6=Sunday
  schedule_days: [0, 2, 4]    # optional multiple days for weekly
  schedule_interval: 120      # minutes (for interval mode)
```

---

## 🧠 Entities (per child)

For each child **N**, these sensors are created:

The IDs below are illustrative. Home Assistant assigns entity IDs from entity names
and its registry; select your actual IDs in **Settings → Devices & Services → Entities**.
Upgrading preserves existing entity IDs and history references. Internal unique IDs
are scoped to each hub automatically.

- **Weekly Plan** – `sensor.mashov_<student_id>_weekly_plan`
- **Homework** – `sensor.mashov_<student_id>_homework`
- **Behavior** – `sensor.mashov_<student_id>_behavior`
- **Timetable** – `sensor.mashov_<student_id>_timetable`
- **Lessons History** – `sensor.mashov_<student_id>_lessons_history` (`…_lesson_history` on new installations)
- **Grades** – `sensor.mashov_<student_id>_grades`

**State** = number of items.
**Attributes** (common): `items`, `formatted_summary`, `formatted_by_date`, `formatted_by_subject` (and for timetable: also table helpers).

Weekly-plan subjects and teachers are filled from timetable groups where available,
and grouped views include the plan text. Dated plans render a date-labelled HTML table
instead of combining different weeks into one grid. Students continue updating after
a class-name change because data lookup follows their stable student ID. Schedule
timestamps use Home Assistant's configured timezone. `last_update` is the
actual last successful refresh time in Home Assistant's timezone, or null for legacy caches without a timestamp.

> **Tip**: Use `{{ state_attr('sensor.mashov_<id>_homework', 'items') }}` to access raw lists.
>
> **Note**: The `items` attribute contains cleaned, size-optimized recent items (technical fields removed). To see all items:
> - `total_items` = total number of items available
> - `stored_items` = number of items in the `items` attribute
> - Full raw data is always available via `coordinator.data` for advanced automations

### School hub entities

Each hub has its own holiday sensor and calendar. Select the matching school's
entities in cards and automations; IDs can have suffixes on installations with multiple hubs.
- **Holidays Sensor** – `sensor.mashov_<school>_holidays_count` on new installations (older: `sensor.mashov_holidays`, `sensor.mashov_holidays_2`, …)
  State = number of holidays. Attributes: `items`, `formatted_summary`, `formatted_by_date`.

- **Holidays Calendar** – `calendar.mashov_<school>_holidays_calendar` on new installations (older: `calendar.mashov_holidays_calendar`, …)
  Full calendar integration for school holidays. Shows events in Home Assistant calendar view with start/end dates.
  _Contributed by [@aviadlevy](https://github.com/aviadlevy)_

---

## 🔔 Automation Blueprint: Daily Homework & Behavior Announcement

A ready-to-use blueprint that speaks today's homework and behavior in Hebrew at a fixed time, with safe defaults and volume handling.

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fmashov_daily_homework_announce.yaml)

If you hit a cache issue when importing, use the commit‑pinned link:

[Import pinned version](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fe9aade5%2Fblueprints%2Fautomation%2Fmashov%2Fmashov_daily_homework_announce.yaml)

Blueprint file location: `blueprints/automation/mashov/mashov_daily_homework_announce.yaml`.

What does it do?
- Daily voice announcement at **15:00** that reads the student’s **name**, **today’s behaviors**, and **today’s homework** (Hebrew).
- Runs **only in daytime** and **skips holidays** using your Mashov holidays sensor (`Items[start/end]`).
- Triggers **only if there is data for today** in the homework and/or behavior sensors.
- Temporarily **sets the speaker to max volume**, speaks via **`tts.speak`** (configurable), then **restores the original volume** after playback.
- Works with any `media_player` (Sonos, Nest, etc.); volume restore is state-aware.
- Fully **templated blueprint**: select your own Mashov sensors and speaker at import time.
- Safe defaults: 15:00 schedule, Hebrew (`he-IL`) TTS, 07:00–22:00 guard rails.
- GitHub-friendly: no hardcoded entity IDs; can be imported with a **My Home Assistant** one-click link.

How to use
1. Click the import button above and select your `holiday_sensor`, `homework_sensor`, `behavior_sensor`, `media_player`, and optional `tts_service`.
2. Save the automation. By default it runs every day at 15:00.

---

## 🎒 Automation Blueprint: Bag Reminder (Tomorrow's Subjects)

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fbag_reminder_tomorrow.yaml)

What does it do?
- Runs once daily at 18:00 to help a student pack their school bag for tomorrow.
- Skips automatically if it’s night-time, Saturday, or a listed holiday (from the holiday sensor).
- Reads tomorrow’s subjects only when timetable data actually exists for tomorrow.
- Builds a Hebrew TTS message: “שלום {Student}… אנא לסדר תיק למחר… {subjects + teacher names [+ plan]}”.
- Temporarily raises the speaker to a configurable max volume, then restores the previous (or fallback) volume after TTS ends.
- Pulls subjects and teacher names from the Mashov timetable; optionally appends each lesson’s “plan” from the weekly plan sensor.
- Waits for the speaker state to finish playing before restoring volume, to avoid cutting the message.
- Provides rich trace/log lines explaining why it ran or skipped (night block, Saturday, holiday, has data).

Blueprint file location: `blueprints/automation/mashov/bag_reminder_tomorrow.yaml`.

How to use
1. Click the import button above, pick your Mashov timetable sensor, (optional) weekly plan sensor, holiday sensor, media player and voice settings.
2. Save the automation. Defaults: 18:00, Hebrew, night guard 22:00–07:00.

---

## 📌 Automation Blueprint: New Noticeboard Notice

Get a phone notification, and optionally hear it on a speaker, when the school posts a new notice
on a child's Mashov noticeboard. Added in v1.0.15.

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fmashov_noticeboard_announce.yaml)

Blueprint file location: `blueprints/automation/mashov/mashov_noticeboard_announce.yaml`.

Requirements
- **Noticeboard** turned on for the hub ([how](#additional-student-data-optional)). Hubs created in v1.0.15 keep it enabled; new setups choose it explicitly.

What does it do?
- Watches one or more noticeboard sensors (one per child). A notice counts as new when its Mashov notice ID was not
  there before, so a notice that replaces another is announced, and a removed notice is not.
- Sends a Home Assistant notification (on by default) and, if you enter one, a phone notification
  (for example `notify.mobile_app_my_phone`). HTML is removed and long notices are shortened.
- Optionally reads the notice aloud in Hebrew: turns the speaker on, raises the volume, speaks with `tts.speak`,
  then restores the previous volume (or a fallback volume if it was unknown).
- **Never speaks during quiet hours, 22:00–07:00.** This is built in and cannot be turned off, so there are no
  surprise announcements at night. A notice that arrives then is still sent as a notification.
- Never re-announces existing notices after a Home Assistant restart, a reload, or a temporary outage.
- Logs every decision to the logbook (announced, quiet hours, nothing new), like the other Mashov blueprints.

Timing: notices arrive with the integration's refresh, not instantly. With the default daily refresh at 14:00,
a morning notice is announced at 14:00. For faster updates, switch the hub to interval mode (for example every
60 minutes) in Configure.

How to use
1. Click the import button above and create an automation from the blueprint.
2. Select the noticeboard sensors, and optionally a phone notify action, a speaker and a TTS engine.
3. Save. Nothing is announced right away; the next new notice triggers it.

---

## ✨ Script Blueprint: Mashov Live dashboard (Bubble Card)

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fscript%2Fmashov%2Fmashov_live_dashboard.yaml)

![Mashov Live dashboard on desktop](docs/images/mashov_live_desktop.png)

<img src="docs/images/mashov_live_mobile.png" alt="Mashov Live dashboard on mobile" width="320">

What does it build?
- A greeting card with the current holiday countdown (or days until the next holiday) and a refresh button.
- One quiet card per student, showing the linked person's photo, a live "tomorrow" line (holiday, Saturday, or the number of lessons and first subjects), behavior, grades and notice counts, and a homework bar.
- A pop-up per student with tomorrow's lessons (teacher and room), recent homework, behavior, grades, notices and the school calendar.
- Hebrew right‑to‑left layout, with English words and numbers kept left‑to‑right.

Who sees which card?
- **Family** (people selected in the General section) see every card.
- Each student card is also visible to the **linked person** and any **extra viewers**, so a child who logs in sees only their own card.
- A child found automatically, with no linked person and no extra viewers, is visible only to the family. Choose at least one family member, or link that child to a person who has a Home Assistant user.
- Only people linked to a Home Assistant user can be used for visibility. This hides cards in the dashboard; it does not restrict access to the underlying entities.

Requirements
- Bubble Card 3.4 or newer (HACS → Frontend).
- An empty UI dashboard: **Settings → Dashboards → Add dashboard → New dashboard from scratch**. Note its URL (for example `mashov-live`).

How to use
1. Click the import button above and create a script from the blueprint.
2. Enter the dashboard URL and the family members. Every child on every Mashov hub is included, with the name, class and sensors the integration already created. The four student sections are optional: type a child's name to set an emoji, color, linked person or extra viewers. Empty sections are skipped.
3. Save and run the script. Run it again after a new child is added; you do not need to edit the script.

The script only writes into a dashboard that is empty or that it built itself. To replace a dashboard
that has other content, or a built-in one such as the Overview (`lovelace`), turn on **Replace existing
content**; the previous content is lost. Only administrators can run the service.

Blueprint file location: `blueprints/script/mashov/mashov_live_dashboard.yaml`.

---

## 🛠️ Services

### `mashov.refresh_now`
Trigger an immediate refresh.
```yaml
service: mashov.refresh_now
data:
  entry_id: YOUR_ENTRY_ID  # optional; if omitted, all entries refresh
```

Calling without `entry_id` refreshes all configured Mashov hubs.

### `mashov.set_options`

Update a hub's options without opening Configure:

```yaml
service: mashov.set_options
data:
  entry_id: YOUR_ENTRY_ID
  schedule_type: weekly
  schedule_time: "14:00"
  schedule_days: [0, 2, 4]  # Monday, Wednesday, Friday
```

For backward compatibility, omitting `entry_id` targets the first loaded hub.
Specify it when selecting a particular hub. The legacy `schedule_day` field remains
supported; supplying it without `schedule_days` replaces the selected days with
that one day. Invalid service inputs are rejected. YAML scheduling overrides still apply.

### `mashov.create_live_dashboard`

Build the Mashov Live dashboard into an existing UI dashboard. With no `students` list it includes every child from every hub. The script blueprint above calls this service; you can also call it directly:

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

## 🧱 Lovelace Cards (Examples)
Ready-made cards live in [`examples/lovelace/cards/`](examples/lovelace/cards/). HACS installs only
`custom_components/`, so copy the cards from GitHub. Full instructions and the placeholder table are in
[examples/lovelace/README.md](examples/lovelace/README.md).

| Card | Shows | Needs |
| --- | --- | --- |
| [`homework_list_by_date.yaml`](examples/lovelace/cards/homework_list_by_date.yaml) | Homework grouped by date | config-template-card, html-card |
| [`behavior_list_by_date.yaml`](examples/lovelace/cards/behavior_list_by_date.yaml) | Behavior events grouped by date | config-template-card, html-card |
| [`weekly_plan_table_advanced.yaml`](examples/lovelace/cards/weekly_plan_table_advanced.yaml) | This week's timetable with plans and holidays | config-template-card, html-card |
| [`weekly_plan_table_dynamic.yaml`](examples/lovelace/cards/weekly_plan_table_dynamic.yaml) | The same, two days at a time with paging (mobile) | config-template-card, html-card |
| [`refresh_all_button.yaml`](examples/lovelace/cards/refresh_all_button.yaml) | Refresh all hubs | nothing |

**How to add a card**
- **UI dashboard (the default):** edit the dashboard → **Add card** → **Manual**, and paste the whole file.
  `!include` does not work in UI dashboards.
- **YAML dashboard:** copy the files to `/config/lovelace/cards/examples/` and include them:
  ```yaml
  views:
    - title: Mashov
      cards:
        - !include lovelace/cards/examples/homework_list_by_date.yaml
  ```

Then replace every placeholder (for example `sensor.mashov_<studentID>_homework`) with your own entity ID.
Each placeholder appears twice in a card: once under `entities` and once inside the JavaScript.
For the weekly cards, use the holiday sensor of the student's own school hub.

Example previews:

<p align="left"><img src="examples/screenshots/weekly_plan_table_advanced.png" alt="Weekly timetable + plan + holidays" width="50%" style="max-width:50%; height:auto;" /></p>
<p align="left"><img src="examples/screenshots/behavior_list_by_date.png" alt="Behavior grouped by date" width="30%" style="max-width:30%; height:auto;" /> <img src="examples/screenshots/homework_list_by_date.png" alt="Homework grouped by date" width="30%" style="max-width:30%; height:auto;" /></p>

## 🔍 Troubleshooting

- **401 / authentication failures**: check credentials and school choice, and update credentials through **Configure**. Password-change responses display a link to the Mashov login page.
- **403 / school-disabled resources**: core resources such as weekly plan retry after 1 hour, then 6 hours, then 24 hours. Each student's resource has its own cooldown, which resets after success. Optional resources use a separate 24-hour cooldown. A school permission denial does not necessarily mean the password is wrong.
- **Startup connection failures**: HA retries transient setup failures when no cached data is available. When cached data exists, the integration retains it until a refresh succeeds.
- **Different host**: open **Options → API base** and paste the base prefix you see in your browser DevTools Network tab (up to `/api/`).
  Common defaults: `https://web.mashov.info/api/`, sometimes `https://mobileapi.mashov.info/api/`.
- **No schools in dropdown**: temporary catalog issue — the flow falls back to text; enter the name or Semel to resolve.
- **Autocomplete not working**: suggestions are limited to 50 schools; type the school name or Semel to search beyond those suggestions.
- **Multiple kids missing**: ensure your account actually lists multiple students in Mashov. Check HA logs for `custom_components.mashov` debug entries.
- **Session errors**: if you see "Unclosed client session" errors, restart Home Assistant to clear any stale connections.
- **"New Device" emails**: session persistence reduces unnecessary logins but cannot prevent fresh authentication after a server-side session expiry. Authentication is saved after successful refreshes in `.storage/mashov.<entry_id>.cache`. Avoid unnecessary reloads and never share this file; it contains authentication data.

### Notifications, GitHub, Telegram and GreenAPI

Authentication and full-refresh failures create a persistent notification in the HA
UI. A successful refresh dismisses that hub's notification. Only detected internal
programming errors offer GitHub reporting; account, network, HTTP/API availability
and school-permission failures do not. The link opens a prefilled issue form for review; publishing or closing an issue
on GitHub does not synchronize its status back into HA.

The integration does not include GitHub issue monitoring or automatic Telegram/
GreenAPI delivery. Configure those separately if needed. To forward HA notifications,
use a `persistent_notification` trigger for added/updated notifications; listening
only for calls to the `persistent_notification.create` service misses notifications
created directly by integration code. For HACS release alerts, monitor the relevant
`update` entities rather than relying on the legacy `sensor.hacs` entity.

### Enable debug logs
```yaml
logger:
  logs:
    custom_components.mashov: debug
```

---

## 🔐 Privacy & Security
- Credentials are stored by Home Assistant in the config entry store.
- The integration mirrors the Mashov web client behavior (headers, cookies, API calls). Endpoints may change without notice.
- Before sharing logs, screenshots, or diagnostics in GitHub issues, review them and remove personal data such as usernames, student names, IDs, grades, homework text, session cookies, tokens, phone numbers, email addresses, and any other sensitive school or account details.
- If you are unsure whether something is safe to share, redact it first. Only upload the minimum data needed to reproduce the problem.

---

## 📄 License
MIT © 2025


---

## 📜 Changelog
See the full changelog in `CHANGELOG.md`.


## v1.0.8: holidays, diagnostics and reporting

Requires Home Assistant **2025.3 or newer**. Restart HA after installing an update.
The regular timetable remains a weekly template. Holiday marking is provided by the
card using the holiday sensor belonging to the student's school. Update both the card's
`entities` list and `holId` / `HL` variable; see [updated examples](examples/lovelace/README.md).

With two school hubs, each has its own holiday sensor (for example `sensor.mashov_holidays` and
`sensor.mashov_holidays_2`). IDs depend on your entity registry.

Authentication failures create a persistent notification immediately. With cached data,
transient refresh failures create a notification after three consecutive failures;
without cached data, setup/refresh failures notify immediately.
For internal errors only, **Review a bug report on GitHub** opens a prefilled form with versions and a technical
event summary. Review, describe the problem and submit on GitHub. This does not publish
anything automatically or upload the HA log. Download integration diagnostics for
additional counts/statuses; diagnostics exclude student records, credentials and entry data.
School-denied optional resources expose `source_status` without repeated failure notifications.

Debug logs can still contain operational context; review existing or manually attached logs.
Never attach raw portal captures or a complete HA log without reviewing personal information.
Raw HTML examples are stored locally under ignored `dataExample/html/`; checked-in examples
use synthetic records. Redacted screenshots remain in the repository.

Development: use Python 3.13/3.14 and the test requirements. On Windows run
`python run_tests.py -q`; the wrapper supplies Unix-only test stubs and permits loopback
for asyncio while keeping external socket connections blocked. Use a compatible
pyOpenSSL/cryptography installation; SSL itself is not mocked.

See [release notes](RELEASE_NOTES.md) and [changelog](CHANGELOG.md).

The project uses the [MIT license](LICENSE); see also the [project notice](NOTICE.md).

Sensor attributes are bounded as a complete JSON payload. If `formatting_truncated` is
true, duplicate formatted groups/HTML may be empty so raw records can fit. If
`items_truncated` is true, compare `stored_items` with `total_items`; the coordinator
retains the full fetched dataset. A single oversized item may be omitted entirely.

## v1.0.9: reliability and upgrade compatibility

Upgrade in HACS and restart Home Assistant. Existing entity IDs and settings are
preserved automatically, including when a student appears in multiple hubs.
Disabled core resources now retry after 1h/6h/24h rather than on every refresh.
Setup reads version metadata already loaded by HA without blocking file reads.
Account setup retains the selected school, closes failed validation sessions, and
applies credential/options changes with one reload. Holiday timestamps with timezone
offsets are supported, and unloading failures preserve the active client and timers.
See [release notes](RELEASE_NOTES.md) for the full fixes and compatibility details.

`mashov.set_options` accepts an optional `entry_id` to choose a hub. For backward
compatibility, omitting it targets the first loaded hub. `mashov.refresh_now`
continues to refresh every hub when `entry_id` is omitted. The legacy
`schedule_day` service field remains supported and replaces the selected days.


## v1.0.10: languages, cache visibility and report fixes

Setup, options, service labels, weekdays and entity names support English, Hebrew,
Arabic, Russian and Ukrainian using Home Assistant's language settings. School-provided
content is unchanged. Existing Hebrew formatted summaries, cards and speech blueprints
remain compatible and are not automatically translated.

Entity names contain the student name only once. Registered entity IDs and user-assigned
names are preserved; newly created IDs may reflect the selected language. Device names
and `student_name` follow class changes. After a successful real login and data refresh
with a nonempty roster, sensor registrations for students no longer in that hub are
removed. Cached, empty or failed rosters never trigger removal. Recorder history is not
purged. Newly returned students receive their sensors without restarting HA.

All student resources expose `source_status`. Failed/blocked sources show `unknown`,
not a misleading zero. Optional 403/404 responses log a warning once per request cycle
and wait 24 hours before retrying. A successful empty result still means zero.
After a failed refresh, cached values remain visible with `data_stale: true` and the
original `last_update`. Holiday failures retain the previous holidays, when available,
and expose their own failure status without discarding fresh student data.

`mashov.set_options` accepts `max_items_in_attributes`, `enabled_data`, legacy `additional_data`,
`mailbox_full_content`, `mailbox_limit`,
`automatic_school_year`, and `HH:MM:SS` as well as `HH:MM`. Legacy unknown fields are
ignored rather than persisted; invalid known values are rejected. Calls without
`entry_id` retain their first-loaded-hub behavior and log a warning if ambiguous.
Deleting a hub also removes its cache and issue notification.

Dated weekly plans render a date-labelled HTML table, keeping different weeks separate.
The recurring timetable retains its weekday grid. Both escape school text in HTML.
Holiday entities remain per hub to preserve existing dashboards and allow hubs to be
removed independently. Downgrading past the v1.0.9 registry migration requires restoring
a matching HA backup; a downgrade does not reverse the unique-ID migration.

See the [17-item review disposition](docs/review-v1.0.10.md) and [release notes](RELEASE_NOTES.md).


## v1.0.11: internal-error reports and optional technical logs

Account/password problems, school-denied resources, timeouts, connection failures,
server HTTP errors and invalid API responses never add a bug-report link. Their
existing recovery notifications and retry behavior remain in place. Unexpected
internal programming exceptions are reportable; automated classification cannot
prove the root cause, so reports still require your review and submission.

An internal error offers two links: **Review a bug report on GitHub** and
**Review a bug report with technical logs**. The second pre-fills the latest error's
UTC timestamp, a standard exception type, integration version and integration source
filenames/line numbers. It excludes exception messages, full paths, local variables,
credentials and portal/student data. This is a sanitized technical event log, not a
copy of the complete Home Assistant log.

For a file attachment, open **Settings → Devices & Services → Mashov**, choose the
affected hub and download diagnostics from its menu. Attach the reviewed JSON file
(or a .txt copy) in the GitHub form's optional **Log files** field. Diagnostics contains
up to 20 internal-error records for that hub from the current HA session; restarting
HA clears this in-memory history. Raw HA debug logs may be attached manually after
reviewing and redacting them. Nothing is posted to GitHub automatically.

Internal errors notify immediately, once per failure sequence. A successful refresh
resets this suppression. The three-failure threshold for transient errors with cached
data is unchanged, and those operational alerts contain no reporting links.


## Removing a departed student and old data (v1.0.12)

Open **Settings → Devices & services → Mashov → the old student device → ⋮ → Delete**.
Removal is allowed when the student is absent from that hub's latest known roster.
A cached roster can be used for this explicit action. If no roster is available,
restore connectivity and refresh first. Active students and holiday devices cannot
be deleted individually because they would be recreated by the integration.

If the hub is pinned to a previous school year, enable **Automatic school year** in
Configure, then refresh. If the old school hub is no longer needed by any student,
delete that hub instead. Moving schools creates a different student identifier;
removing the old card does not remove the new-school student.

Automatic cleanup requires a successful refresh after a fresh login, a nonempty
roster and fresh data. It removes departed students' sensor registrations and empty
device cards for that hub. Restoring an authenticated cached session does not prove
that the roster is current; explicit deletion remains available for absent students.
Devices shared with another hub keep that other association.

| Data | Removal / retention behavior |
| --- | --- |
| Student device and entities | Removed from HA's registries for the selected hub. Data on Mashov's servers is untouched. |
| Local data cache | Each successful refresh replaces the hub snapshot. Failed refreshes keep the last successful data; holiday failures can retain earlier holiday data. No age-based cache purge runs. Deselected data and disabled message bodies are removed on reload before authentication, even if the next refresh fails. |
| Saved authentication | Stored with the hub cache. Removing an individual orphan card does not reset the hub's session. Deleting the hub removes its entire cache and saved authentication. |
| Homework and behavior | Requests use the configured date window, by default 7 days back and 21 forward. This is not a Recorder deletion policy. |
| Other student resources | Follow the data returned by Mashov for the selected year/session; there is no global age-based purge of grades or lesson records. |
| Entity attributes | `max_items_in_attributes` and byte limits restrict the displayed payload, not the full cache or recorded history. |
| HA history | Governed independently by your Recorder configuration. Deleting devices, entities or hubs does not invoke a history purge. Back up HA before any intentional Recorder purge. |

The integration does not silently erase historical records when a child changes
class or school. Recorder retention must be checked in the user's HA configuration;
the integration does not override it.

Regenerating a Mashov-generated dashboard replaces its saved configuration, including manual edits made after generation. Selected family persons must include at least one linked Home Assistant user. Student popup links are scoped to their hub as well as student ID.
