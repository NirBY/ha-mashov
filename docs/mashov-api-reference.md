# Mashov parent-portal API reference (sanitized)

Source app: `https://web.mashov.info/students/` (Angular, build `main-N7LS6LMW.js`, 38 JS chunks).
Collected 2026-11-17 by (A) static extraction of every `${MashovApiUrl}…` call site in the bundle and (B) live capture while browsing the parent portal read-only.

- Base URL: `https://web.mashov.info/api/` (bundle constant `MashovApiUrl`). WebSocket base: `wss://web.mashov.info/api/`.
- `MashovApiVersion` constant: `3.20210425`. It is sent in the **login body**, not as a header.
- Placeholders: `<STUDENT_GUID>` (child, `accessToken.children[].childGuid`), `<PARENT_GUID>` (`credential.userId`), `<CONVERSATION_ID>`, `<MESSAGE_ID>`, `<FILE_ID>`, `<FILE_NAME>` (URL-encoded), `<ACTIVITY_ID>` (number), `<FORM_ID>`, `<MAAKAV_ID>`, `<REQUEST_ID>`.
- Schema notation: `guid`, `datetime` (ISO `YYYY-MM-DDTHH:mm:ss`, no zone unless noted), `string`, `number`, `boolean`. `number(1)` = number whose observed value was `1` (enum/flag fields only). `[ {...}, …N ]` = array of N, first element shown.
- "Live" = request observed from the real app while browsing, or fetched with the same session and confirmed `200`. "Bundle-only" = present in the JS but not exercised.
- Many lists were empty for this account (early school year, school blocks some screens for parents). Empty-list schemas are marked as such.

---

## 1. Endpoint table

Side effects: `none` / `marks read` / `writes`. Rows marked ⚠ are calls the app fires **automatically** on page load.

### Auth / session / shell (loaded on every page)

Remembered-device renewal (issue #33, reporter's live findings): a password login
with `appName: com.mashov.main` and `isPrivateDevice: true` can return a JSON
`devicePass` header containing `appName, deviceUuid, pass, semel, userId, year`,
plus a required `uniquId` cookie. `POST loginDevice` sends the app/version/device
metadata from password login (including `apiVersion` and `devicePlatform`) in its
JSON body, the compact complete pass object in the `devicePass` header, and the
cookie. The school/year/user fields belong in that header, not the body. Omitting
`devicePlatform` returns 400; omitting version metadata can return 401 with
"Internal error." This was verified against a local account on 2026-11-24.
It returns normal session cookies, CSRF and
children. The integration first reuses valid sessions, then tries this renewal.
Any 4xx except 408/429 (and a 200 without a session) drops the pass and falls back
to password login, so a revoked pass or a changed route can never block refreshes;
a forced password change is still reported as such. Network failures, 408/429,
5xx, redirects and non-JSON pages are temporary and preserve the pass.
Device credentials are scoped to the account, API address, school and year;
credential and API-address changes clear them. They are secrets and must never be
included in logs or diagnostics. Hub clients persist them even if the subsequent
data fetch fails. Every login identifies as the app (`com.mashov.main`). The
add-hub and Configure checks also tick "private device" and hand their session and
pass to the hub in memory, so a new hub or new credentials cost one password login
(and one "new device" email), not two. Closing the HTTP session must not call
`logout`, which reportedly revokes the pass.

The Mashov Android app (3.8.72, read from its bundle) confirms this: it is the same
Angular bundle as the website, with `MashovAppId` switching between
`com.mashov.main` and `info.mashov.students`, so both use the same data routes.
Every login route (`login`, `loginDevice`, `loginBiometric`) goes through one
`prepareLoginData`, which adds `appName, apiVersion, appVersion, appBuild,
deviceUuid, devicePlatform, deviceManufacturer, deviceModel, deviceVersion,
registrationId`. The app sends its stored pass as `devicePass: JSON.stringify(pass)`
on any login and replaces it whenever a response carries a new one.
`isPrivateDevice` is the login form's "private device" checkbox, unset by default.
When a renewal fails, the app asks for the password again. It calls `logout` only on
an explicit sign-out. The app sends `apiVersion` `3.20210425`; `GET schools` currently
answers `ApiVersion: 3.20200528`, and the app only warns when the server's value is higher.

| Method | Path | Purpose | Side effects | Captured live? |
|---|---|---|---|---|
| POST | `login` | Username/password login. Body includes `semel, year, username, password, appName, apiVersion, appVersion, appBuild, deviceUuid, devicePlatform, deviceManufacturer, deviceModel, deviceVersion` | writes (creates session) | bundle-only |
| POST | `login/mfa/send` | Send MFA code. Body `{challengeId, method}` | writes | bundle-only |
| POST | `login/mfa/verify` | Verify MFA | writes | bundle-only |
| GET | `clearSession[/<id>]` | Clears previous session before login | writes | bundle-only |
| GET | `logout` | Log out | writes | bundle-only |
| GET | `session/isActive` | Session keep-alive check (empty body) | none | yes |
| GET | `idm/token` | IDM (Ministry SSO) token. Returns 404 when not logged in through IDM | none | yes (404) |
| GET | `schools` | All schools `[{semel, name, years[]}]` (~2.8k entries) | none | yes |
| GET | `user/notifications?skip=0&take=7` | Bell notifications (list only) | none | yes |
| PUT | `user/notifications/` | Mark given notifications read. **Sent automatically when the Notifications page or bell list is opened** | marks read ⚠ | bundle-only (not triggered) |
| PUT | `user/notifications/readAll` | Mark all notifications read | marks read | bundle-only |
| GET | `adminmessages/popup` | Mashov admin popups | none | yes |
| GET | `help/links` | Contextual help links | none | yes |
| GET | `shahaf/coolSite` | URL of the school's Shahaf "cool site" (exams/events board). `text/plain`, empty for this school | none | yes |
| GET | `user/<PARENT_GUID>/picture` | Avatar image | none | yes |
| PUT | `consent` | Cookie/analytics consent. Body `{didConsent: boolean, consentDate: datetime}`. **Fired automatically on first page load after login** | writes ⚠ | yes |
| GET | `hebrewDates` | Map `{ "<ISO date>": "<hebrew date string>" }` | none | yes |
| PUT | `displayNames` | Resolve GUIDs → display names (lookup, uses PUT). Fired by the Files page | none (lookup) | yes |

### Approvals / forms / trips

| Method | Path | Purpose | Side effects | Captured live? |
|---|---|---|---|---|
| GET | `schoolActivities/permitted` | **Trip/activity approval list (אישורי הורים לפעילות)** | none | yes |
| GET | `schoolActivities/<ACTIVITY_ID>/permitted` | Single activity (same shape, 1-element array) | none | yes |
| GET | `schoolActivities/<ACTIVITY_ID>/userAnswers` | This parent's answer(s) per child for the activity | none | yes |
| GET | `schoolActivities/<ACTIVITY_ID>/answers` | All answers (staff) | none | yes (403 for parent) |
| GET | `schoolActivities` | Staff list | none | yes (403 for parent) |
| PUT | `students/<STUDENT_GUID>/schoolActivities/<ACTIVITY_ID>` | **Submit approval answer** | writes | bundle-only |
| PUT | `digitalApproval/<PARENT_GUID>` | Parent's yearly "digital approval" declaration. Body empty. Returns the new `isDigitalApproved` year list | writes | bundle-only |
| URL | `schoolActivities/<ACTIVITY_ID>/files/<FILE_ID>/<FILE_NAME>` | Activity attachment download | none (assumed) | bundle-only |
| GET | `user/forms?isParentsConsent=true` | **Parent consent questionnaires (שאלוני הורים מקוונים)** | none | yes (empty list) |
| GET | `user/forms?isParentsConsent=false` | Online forms (טפסים מקוונים) | none | yes (empty list) |
| GET | `user/forms/unanswered` | Unanswered forms | none | yes (empty list) |
| GET | `user/forms/unanswered?<query>` | Unanswered count variant | none | bundle-only |
| GET | `forms/<FORM_ID>` | Form detail | none | bundle-only |
| GET | `forms/<FORM_ID>/answer[/<answererGuid>]` | My saved answer | none | bundle-only |
| PUT | `forms/<FORM_ID>/answer` | **Submit form answer** | writes | bundle-only |
| GET | `students/<STUDENT_GUID>/parentsConsent` | Per-student consent forms | none | yes (403 for parent) |
| GET | `students/<STUDENT_GUID>/studentReleases` | Early-release requests (שחרורית) | none | yes (empty list) |
| GET | `students/<STUDENT_GUID>/studentReleases/<id>/validate` | Validate release request | none | bundle-only |
| PUT | `students/<STUDENT_GUID>/studentRelease[/<id>]/request` | Create/update release request | writes | bundle-only |
| PUT | `students/<STUDENT_GUID>/studentRelease/<id>/response?<query>` | Respond to release request | writes | bundle-only |
| DELETE | `students/<STUDENT_GUID>/studentRelease/<id>` | Delete release request | writes | bundle-only |
| GET | `parents/<PARENT_GUID>/meetings` | Parent-teacher meetings, all children | none | yes (empty list) |
| GET | `parents/<PARENT_GUID>/children/<STUDENT_GUID>/meetings` | Meetings for one child (ניהול ימי הורים) | none | yes (empty list) |
| GET | `meetings/parents/<PARENT_GUID>/meetings[/<STUDENT_GUID>]/details` | Mobile-app variant of the above | none | bundle-only |

### Mail and attachments

| Method | Path | Purpose | Side effects | Captured live? |
|---|---|---|---|---|
| GET | `mail/counts[?$select=<field>]` | Folder counters (dashboard uses `$select=unreadConversations`) | none | yes |
| GET | `mail/<folder>/conversations?skip=&take=` | Conversation list. Folders: `inbox, archive, updates, sent, deleted, draft, unread`. Total in `X-Conversations-Count` header | none | yes |
| GET | `mail/unread/conversations?take=5` | Unread conversations (dashboard widget) | none (observed) | yes |
| GET | `mail/conversations?isNew=&isDeleted=&skip=&take=` | All folders | none | bundle-only |
| GET | `mail/labels` | User labels | none | yes |
| GET | `mail/labels/<labelId>/conversations?…` | By label | none | bundle-only |
| GET | `mail/search[/<text>]/conversations?skip=&take=` | Search | none | bundle-only |
| GET | `mail/conversations/<CONVERSATION_ID>` | **Conversation detail incl. message bodies** | marks read (inferred) | yes (already-read conversation only) |
| GET | `mail/messages/<MESSAGE_ID>` | Single message incl. body | marks read? (unknown) | yes (already-read message only) |
| GET | `mail/messages/<MESSAGE_ID>/recipients[/<x>]` | Recipients | none | yes (403 for parent) |
| URL | `mail/messages/<MESSAGE_ID>/files/<FILE_ID>/download/<FILE_NAME>` | **Attachment download** (plain `<a href>`) | unknown | bundle-only (no attachments in mailbox) |
| PUT | `mail/conversations/markAsRead` | Body: `[<CONVERSATION_ID>, …]` | marks read | bundle-only |
| PUT | `mail/conversations/markAsUnread` | Body: `[<CONVERSATION_ID>, …]` | writes | bundle-only |
| PUT | `mail/conversations/labels` | Set labels | writes | bundle-only |
| PUT | `mail/conversations/move/<folder>` | Move | writes | bundle-only |
| PUT | `mail/conversations/restore` | Restore from deleted | writes | bundle-only |
| PUT | `mail/conversations/delete[?isHardDelete=]` | Delete | writes | bundle-only |
| PUT | `mail/messages/delete[?isHardDelete=]` | Delete messages | writes | bundle-only |
| DELETE | `mail/messages/<MESSAGE_ID>` | Delete message | writes | bundle-only |
| POST | `mail[/conversation/<CONVERSATION_ID>]/messages[/<MESSAGE_ID>]` | Send / reply | writes | bundle-only |
| PUT | `mail/conversations[/<CONVERSATION_ID>[/messages/<MESSAGE_ID>]]/draft` | Save draft | writes | bundle-only |
| POST | `mail/messages/<MESSAGE_ID>/files` | Upload attachment (multipart, field `fileUpload`) | writes | bundle-only |
| PUT | `mail/messages/<MESSAGE_ID>/copyFiles` | Copy attachments (forward) | writes | bundle-only |
| GET | `mail/recipients?semel=&year=` | Address book | none | bundle-only |
| POST | `mail/recipients?semel=&year=` | Expand recipient groups (lookup) | none (lookup) | bundle-only |

### Student data (per child)

| Method | Path | Purpose | Side effects | Captured live? |
|---|---|---|---|---|
| GET | `students/<STUDENT_GUID>/timetable` | Weekly timetable | none | yes |
| GET | `students/<STUDENT_GUID>/timetable/changes?start=&end=` | **Timetable changes and cancellations (שינויים במערכת)** | none | yes |
| GET | `timetable` | Generic timetable | none | bundle-only |
| GET | `bells` | Bell schedule | none | yes |
| GET | `holidays` | School holidays | none | yes |
| GET | `students/<STUDENT_GUID>/homework` | Homework (with `files[]` when present) | none | yes |
| GET | `students/<STUDENT_GUID>/behave[?start=&minimal=true]` | Behavior events in class | none | yes |
| GET | `students/<STUDENT_GUID>/outBehave[?start=]` | Out-of-class behavior | none | yes (empty list) |
| GET | `students/<STUDENT_GUID>/dailyBehave` | Daily behavior events | none | yes (empty list) |
| GET | `students/<STUDENT_GUID>/countBehave…`, `dailyBehaveCount` | Counters | none | bundle-only |
| GET | `achvas` | Behavior-code dictionary | none | yes |
| GET | `students/<STUDENT_GUID>/groups` | Child's groups/classes + teachers | none | yes |
| GET | `students/<STUDENT_GUID>/lessonsCount[?start=]` | Lessons held and weekly hours per group (not absences or lateness) | none | yes |
| GET | `students/<STUDENT_GUID>/grades[?start=]` | Regular grades | none | yes (empty list; screen blocked by school) |
| GET | `students/<STUDENT_GUID>/gradingEvents` | **Graded events/exams with dates (`eDate`)** | none | yes |
| GET | `students/<STUDENT_GUID>/grades/groupsAvarge` | Group averages | none | bundle-only |
| GET | `students/<STUDENT_GUID>/gradingPeriods` | Grading periods | none | bundle-only |
| GET | `students/<STUDENT_GUID>/messageBoard` | **Noticeboard** for the child | none | yes |
| GET | `students/<STUDENT_GUID>/maakav[?start=&end=&allYears=]` | **Follow-up notes (הערות מעקב)** | none | yes (empty list) |
| URL | `students/<STUDENT_GUID>/maakav/<MAAKAV_ID>/files/<FILE_ID>/<FILE_NAME>` | Follow-up attachment download | unknown | bundle-only |
| GET | `parentMaakav/<MAAKAV_ID>/maakav` | Follow-up conversation thread | unknown | bundle-only |
| GET | `students/<STUDENT_GUID>/justificationrequests[?…]` | Absence justification requests | none | yes (503 for this school) |
| URL | `students/<STUDENT_GUID>/justificationrequests/<REQUEST_ID>/files/<FILE_ID>/<FILE_NAME>` | Justification attachment | unknown | bundle-only |
| PUT / DELETE / POST | `students/<STUDENT_GUID>/justificationRequests`, `…/justificationrequests/<id>`, `…/justificationrequests/<id>/files` | Create / delete / upload | writes | bundle-only |
| GET | `students/<STUDENT_GUID>/futureJustifications` | Future justifications | none | yes (403) |
| GET | `students/<STUDENT_GUID>/files[?…]` | Student file space (מרחב קבצים) | none | yes (empty list) |
| GET | `students/files/labels` | File label bank | none | yes (empty list) |
| URL | `students/<STUDENT_GUID>/files/<FILE_ID>/<FILE_NAME>` | File download | unknown | bundle-only |
| GET | `students/<STUDENT_GUID>/studyFiles` | Study material (חומרי לימוד) | none | yes (empty list) |
| URL | `students/<STUDENT_GUID>/studyFiles/<FILE_ID>/<FILE_NAME>` | Study file / homework file download | unknown | bundle-only |
| GET | `students/<STUDENT_GUID>/hatamot` | Accommodations (התאמות) | none | yes (empty list) |
| GET | `students/<STUDENT_GUID>/bagrut/hatamot` | Bagrut accommodations | none | yes (empty list) |
| GET | `students/<STUDENT_GUID>/bagrut/grades`, `/bagrut/subjectGrades`, `/bagrut/sheelonim`, `/bagrut/achievements`, `/bagrut/statuses` | Bagrut | none | grades: yes (empty list); rest bundle-only |
| GET | `students/<STUDENT_GUID>/specialHoursLessons` | Individual lessons (שעות פרטניות) | none | yes (empty list) |
| GET | `students/<STUDENT_GUID>/reportCards` | Report-card PDFs (תעודות) | none | yes (empty list) |
| GET | `students/<STUDENT_GUID>/moodle/{assignments,quizzes,lti}/grades` | Moodle grades | none | yes |
| GET | `students/<STUDENT_GUID>/alfon` | Class phone list | none | yes (403, `hasParentsAlfon` off) |
| GET | `students/<STUDENT_GUID>/details`, `/siblings`, `/treatingteam`, `/goals` | Staff-side details | none | yes (403 for parent) |
| GET | `students/<STUDENT_GUID>/lessons/history`, `/lessons/plans` | Lesson history / weekly plan | none | bundle-only |
| GET | `user/<STUDENT_GUID>/picture` | Child photo (read; verified live with the child GUID) | none | yes |
| POST | `students/<STUDENT_GUID>/picture` | Child photo upload (never called by this integration) | writes | bundle-only |
| GET | `bbb?start=&end=` | Online classes (כיתה מקוונת) | none | yes |
| GET | `bbb/recordings` | Recordings | none | yes (empty list) |
| GET | `healthCheck/culture` | Fired by the BBB page | none | yes |

### User / profile

| Method | Path | Purpose | Side effects | Captured live? |
|---|---|---|---|---|
| GET | `user/details` | Parent's contact details | none | yes |
| GET | `user/settings` | Settings incl. `isDigitalApproved` years | none | yes |
| PUT | `user/settings/<key>` | Change a setting | writes | bundle-only |
| GET | `user/devices` | Logged-in devices | none | yes |
| PUT / DELETE | `user/devices/<id>`, `user/devices/biometric` | Manage devices | writes | bundle-only |
| GET | `user/bindings` | Linked accounts | none | yes (empty list) |
| GET | `push/options` | Push bitmask (`number`) | none | yes |
| PUT | `push/options`, `push/registrationId` | Push settings | writes | bundle-only |
| GET | `user/<STUDENT_GUID>/birthday` | Birthday banner | none | yes |
| GET | `user/alerts`, `user/<guid>/accessInfo`, `importantMessages`, `whatsNew/counts`, `schoolLinks` | Staff features | none | yes (403 for parent) |
| POST | `user/password`, `user/email`, `user/cellphone`, `user/username`, `user/otp…`, `user/recover`, `user/reset…` | Account management | writes | bundle-only |

---

## 2. Details per group

### 2.1 Required headers and auth (Q6)

- **Cookies.** The session is held in HttpOnly cookies (nothing is visible to `document.cookie`). The Angular interceptor sets `withCredentials: true` on every `MashovApiUrl` request.
- **`X-Csrf-Token`.** Returned as a response header of `POST login`. The app stores it in `localStorage["X-Csrf-Token"]` and the interceptor appends it to **every** API request (`main-*.js`, `intercept()`).
- **No `apiVersion` header.** `apiVersion` (`"3.20210425"`), `appName`, `appVersion`, `appBuild` and `device*` fields go in the **login JSON body**.
- **Optional headers:**
  - `devicePass` / `deviceBiometric`: request headers used only for mobile "remember device" or biometric login.
  - `X-Conversations-Count`: response header on mail list endpoints. It holds the total count for paging.
  - `X-Notifications-Count` and `X-UnreadNotifications-Count`: response headers on `user/notifications`.
- **Downloads.** File URLs are plain `GET`s that the browser opens through `<a href>`. They rely on the session cookie; the CSRF header is not attached on a link navigation. Whether the server *requires* the CSRF header for downloads is **not verified**.
- **Error codes.** `403 {message: string}` is returned for screens the parent role or school settings deny. `503` was returned by `justificationrequests` for this school.

Login response body schema (`accessToken`, stored in `sessionStorage["students-accessToken"]`):

```json
{
  "children": [{ "childGuid": "<STUDENT_GUID>", "classCode": "string", "classNum": 0, "familyName": "<NAME>", "privateName": "<NAME>", "gender": "string", "groups": [0] }],
  "displayName": "<NAME>", "username": "<USERNAME>", "gender": "string",
  "externChildren": [], "inactiveChildren": [], "networks": [], "roles": [], "rolePermissions": [],
  "lastLogin": "datetime", "lastPassSet": "datetime",
  "schoolOptions": { "hasParents": true, "hasParentsAlfon": false, "hasParentsBehave": true, "hasParentsMaakav": true, "hasParentsOutgoingMail": true, "hasParentsPeriodicGrades": true, "hasParentsRegularGrades": true, "hasBagrutGrades": true, "schoolName": "<SCHOOL>", "schoolYears": [0], "maxGrade": 0, "...": "≈40 boolean flags" },
  "schoolSettings": { "allowStudentsReleases": true, "denyStudentsMaakav": false, "denyStudentsTimeTable": false, "schoolYear": 0, "principalId": "<GUID>", "...": "≈25 flags" },
  "userSchoolYears": [0], "userSchools": [],
  "userSettings": { "detailsState": 0, "emailNotifications": true, "isDigitalApproved": [2025], "pushOptions": 0 }
}
```

`credential` (in `sessionStorage["students-credential"]`):

```json
{ "sessionId": "<GUID>", "userId": "<PARENT_GUID>", "idNumber": "<ID_NUMBER>", "userType": 5, "roleUserType": 0, "schoolUserType": 2,
  "idp": "string", "hasAuthenticated": true, "hasStronglyAuthenticated": true, "semel": "<SEMEL>", "year": 0,
  "displayName": "<NAME>", "correlationId": "<GUID>", "username": "<USERNAME>", "authTime": "datetime", "lastActivity": "datetime" }
```

`userType: 5` = parent (observed).

### 2.2 Approvals: trips and activities (`schoolActivities`)

This is the "אישורי הורים לפעילות" menu item, route `/main/schoolActivities`.

`GET schoolActivities/permitted` (live, 2 items):

```json
[{
  "id": 0,
  "createTime": "datetime",
  "activityStartDate": "datetime",
  "activityEndDate": "datetime",
  "activityType": 1,
  "creatorGuid": "<GUID>",
  "title": "<TITLE>",
  "description": "<HTML>",
  "endAnswerDate": "datetime",
  "isAnswered": true
}]
```

- `activityType`: `1` = סיור/טיול (trip), `4` = סל תרבות. Any other value is labelled "פעילות בית ספרית" (school activity). Source: `assets/i18n/he.json` → `shared.schoolActivities.activityType`.
- `description` is HTML. The app sanitizes it before rendering.
- The UI computes the number of days from `activityStartDate`/`activityEndDate`. It locks answering once `now > endAnswerDate` (`isActivityPassedAnswerDate`).
- Some activities carry an `activityData` JSON string with extra `questions[]` (`{id, answer}`) that the answer page renders. This was not present in the live sample. **Not verified.**
- There are **no price or payment fields**, in the live data or in the bundle.
- **Verified live (2026-11-17):** in `GET schoolActivities/<id>/userAnswers`, `schoolActivityAnswer.studentGuid` (and the entry's `userId`) equals the child's `accessToken.children[].childGuid`. Answer shape: `{activityId: number, userId: string, studentGuid: string, answerTime: string, answer: number, manuallyAnswered: boolean}`.

`GET schoolActivities/<ACTIVITY_ID>/userAnswers` (live):

```json
[{
  "userId": "<PARENT_GUID>",
  "schoolActivityAnswer": {
    "activityId": 0,
    "userId": "<PARENT_GUID>",
    "studentGuid": "<STUDENT_GUID>",
    "answerTime": "datetime",
    "answer": 1,
    "manuallyAnswered": false
  }
}]
```

There is one entry per child the activity applies to. Values of `answer`:

| Value | Meaning |
|---|---|
| `1` | approved |
| `2` | approved with health conditions |
| `3` | denied |
| missing / `null` | unanswered ("ללא מענה") |

The UI also binds `schoolActivityAnswer.remark` (string) and `answerData` (JSON string of question answers).

`PUT students/<STUDENT_GUID>/schoolActivities/<ACTIVITY_ID>` (bundle-only, **writes**). The body is the `schoolActivityAnswer` object above, with `answer`, `remark` and `answerData` set.

Digital approval gate (important for automation):
- On the answer page, a parent whose `userSettings.isDigitalApproved` does not include the current school year gets a confirm dialog.
- Pressing "אישור" sends `PUT digitalApproval/<PARENT_GUID>` (empty body), which is a write. Pressing "דחייה" navigates away.
- The list endpoint (`schoolActivities/permitted`) does **not** trigger this dialog. It is safe to poll.

### 2.3 Approvals: forms and consent questionnaires (`forms`)

- **List.** `GET user/forms?isParentsConsent=true` returns consent questionnaires (route `/main/parentsConsentForms`). `isParentsConsent=false` returns general online forms (route `/main/forms`). Both were empty for this account.
- **Fields the UI reads** (bundle only):
  - `formId`, `formData` (JSON string, parsed client-side into `{questions:[{…, isMust, isMultipleAnswer}]}`), `createTime`, `endTime` (due date; sorted by `-hasEndTime, endTime, -createTime`), `isAnswered`.
  - The answer object has `answerData` / `answers`.
- **Detail.** `GET forms/<FORM_ID>`. My answer: `GET forms/<FORM_ID>/answer`. Submit: `PUT forms/<FORM_ID>/answer` (**writes**).
- **Status.** No explicit status enum was found. Pending vs. done is `isAnswered`, and expired is `now > endTime`. **Not verified live.**

### 2.4 Mail

Folder list `GET mail/inbox/conversations?skip=0&take=20` (live):

```json
[{
  "conversationId": "<CONVERSATION_ID>",
  "subject": "<SUBJECT>",
  "sendTime": "datetime",
  "isNew": false,
  "hasDrafts": false,
  "hasAttachments": false,
  "preventReply": false,
  "labels": [],
  "messages": [{
    "messageId": "<MESSAGE_ID>", "conversationId": "<CONVERSATION_ID>",
    "senderId": "<GUID>", "senderName": "<NAME>", "subject": "<SUBJECT>",
    "lastUpdate": "datetime", "sendTime": "datetime",
    "folder": 0, "isNew": false, "isDeleted": false,
    "sendOnBehalf": false, "sendViaEmail": false, "sendViaSms": false,
    "preventReply": false, "sentViaEmail": false, "sentViaSms": false
  }]
}]
```

- **Unread state.** `isNew` on the conversation and on each message is the unread flag. The response header `X-Conversations-Count` holds the total.
- **No message bodies** in list responses.
- **`folder` enum** (`ZB` in the bundle): `0` Draft, `1` Sent, `2` Inbox, `3` Archive, `4` Updates.
- **Folder URL names:** `inbox, archive, updates, sent, deleted, draft, unread, search`.

Detail `GET mail/conversations/<CONVERSATION_ID>` (live, already-read conversation). It has the same shape as a list item, plus `body` (HTML string) and `labels` on each message. When a message has attachments, the compose and view components read `message.files: [{ fileId, fileName }]`. **Not observed live**, because the mailbox had no attachments.

`GET mail/messages/<MESSAGE_ID>` (live) returns one message object with `body`.

`GET mail/counts`:

```json
{ "allMessages": 0, "draftMessages": 0, "inboxMessages": 0, "archiveMessages": 0, "updatesMessages": 0, "sentMessages": 0,
  "readMessages": 0, "unreadMessages": 0, "newMessages": 0, "deletedMessages": 0,
  "allConversations": 0, "draftConversations": 0, "inboxConversations": 0, "archiveConversations": 0, "updatesConversations": 0,
  "sentConversations": 0, "readConversations": 0, "unreadConversations": 0, "newConversations": 0, "deletedConversations": 0 }
```

Attachment download URL (built client-side in `getFileUrl`):

```
GET https://web.mashov.info/api/mail/messages/<MESSAGE_ID>/files/<FILE_ID>/download/<encodeURIComponent(FILE_NAME)>
```

### 2.5 Student data schemas (live)

`GET students/<STUDENT_GUID>/timetable` (39 items):

```json
[{ "timeTable": { "groupId": 0, "day": 0, "lesson": 0, "roomNum": "string", "weeks": 0 },
   "groupDetails": { "groupId": 0, "groupName": "string", "subjectName": "string",
                     "groupTeachers": [{ "teacherGuid": "<GUID>", "teacherName": "<NAME>" }], "groupInactiveTeachers": [] } }]
```

`GET students/<STUDENT_GUID>/timetable/changes?start=<YYYY-MM-DD>T00:00:00&end=<YYYY-MM-DD>T00:00:00` (verified 2026-11-24 on two schools; same session cookies and `X-Csrf-Token` as the other student routes):

```json
{ "isEnabled": true, "changes": [],
  "cancellations": [{ "lessonDate": "datetime", "lesson": 0, "groupId": 0, "cancellationReason": "<TEXT>" }] }
```

- One school answered `isEnabled: true` with cancellations for both children between September 1 and November 19, each with a reason. None was dated after the day of the check.
- The other school answered `isEnabled: false` with empty lists. The integration treats that as "not offered by this school", not as an error.
- `groupId` matches `timeTable.groupId` / `groupDetails.groupId` in the timetable and `groupId` in `groups`.
- `cancellationReason` is free text written by staff and may contain names. One row seen the same day carried an integer instead, apparently a reason code whose meaning is not published; the integration keeps it as `reason_code`.
- `changes` (substitutions) was empty on both schools, so its item shape is **not verified**.

`GET bells`:

```json
[{ "lessonNumber": 0, "startTime": "HH:mm", "endTime": "HH:mm" }]
```

`GET holidays`:

```json
[{ "id": 0, "hollyDayName": "string", "startDate": "datetime", "endDate": "datetime" }]
```

`hollyDayName` is the server's spelling.

`GET students/<STUDENT_GUID>/homework`:

```json
[{ "lessonId": 0, "lessonDate": "datetime", "lesson": 0, "homework": "<TEXT>", "groupId": 0, "remark": "<TEXT>",
   "studentGuid": "<STUDENT_GUID>", "subjectName": "string" }]
```

When there are attachments the UI also reads `files: [{fileId, fileName}]` and links them via `studyFiles/<FILE_ID>/<FILE_NAME>`.

`GET students/<STUDENT_GUID>/behave`:

```json
[{ "studentGuid": "<STUDENT_GUID>", "eventCode": 0, "justified": 0, "lessonId": 0, "reporterGuid": "<GUID>",
   "timestamp": "datetime", "groupId": 0, "lessonType": 1, "lesson": 0, "lessonDate": "datetime", "lessonReporter": "<GUID>",
   "achvaCode": 0, "achvaName": "string", "achvaAval": 0, "justificationId": 0, "justification": "string",
   "reporter": "<NAME>", "subject": "string" }]
```

`GET achvas`:

```json
[{ "code": 0, "name": "string", "hidden": false, "achvaType": 1, "commonBehaveId": 0, "onDuplicateLesson": false,
   "onLastBehave": false, "aval": 0, "displayOrder": 0, "teacherId": 0, "justifiable": true, "hideFromStudents": false,
   "preventPush": false, "preventTeachersPush": false, "showInBehave": true }]
```

`GET students/<STUDENT_GUID>/groups`:

```json
[{ "groupId": 0, "groupName": "string", "subjectName": "string",
   "groupTeachers": [{ "teacherGuid": "<GUID>", "teacherName": "<NAME>" }], "groupInactiveTeachers": [] }]
```

`GET students/<STUDENT_GUID>/lessonsCount`:

```json
[{ "studentGuid": "<STUDENT_GUID>", "groupId": 0, "lessonsCount": 0, "weeklyHours": 0 }]
```

`GET students/<STUDENT_GUID>/messageBoard` (noticeboard):

```json
[{ "eventid": 0, "eventtext": "<HTML>", "font": "string", "color": "string", "expirationDate": "datetime", "inSite": true }]
```

`GET students/<STUDENT_GUID>/gradingEvents` (exams and graded events):

```json
[{
  "group": {
    "group": { "groupId": 0, "groupType": 1, "subjectName": "string", "groupName": "string", "startDate": "datetime", "endDate": "datetime",
               "lastUpdate": "datetime", "moeSubject": 0, "moeGroupPeriod": 0, "moeEducationLevel": 1 },
    "groupTeachers": [{ "teacherId": 0, "teacherGuid": "<GUID>", "teacherName": "<NAME>", "privateName": "<NAME>", "familyName": "<NAME>", "gender": "string", "isMoeEmployee": false }],
    "groupInactiveTeachers": [],
    "groupProperties": { "groupId": 0, "targetClasses": "string", "isPartial": false, "isDeleted": false, "openRepCard": true, "shahafProfileId": 0, "shahafSubjectName": "string" }
  },
  "gradingEvent": { "id": 0, "name": "string", "groupId": 0, "eDate": "datetime", "startLesson": 0, "endLesson": 0, "rate": 0,
                    "gradingPeriod": 0, "gradeType": 0, "visiblefrom": "datetime", "showRateInStudents": true,
                    "showComponentsInStudents": true, "isDraft": false, "creatorId": "<GUID>" },
  "gradeType": { "id": 0, "name": "string", "displayOrder": 0 },
  "year": 0
}]
```

`GET user/notifications?skip=0&take=7`:

```json
[{ "id": 0, "userId": "<GUID>", "appName": "string", "eventTime": "datetime", "eventType": 102, "eventText": "<TEXT>",
   "eventKey": "string", "eventData": "<JSON string>", "eventUserId": "<GUID>", "addTime": "datetime" }]
```

The response also carries the headers `X-Notifications-Count` and `X-UnreadNotifications-Count`. A notification is unread when `readTime` is absent (the client filters with `!readTime`).

`eventType` values (Mashov app 3.8.72 bundle): 1 Text, 11 CantRecover, 16 UnreadConversations, 101 Behave, 102 Homework, 105 BehaveOutside, 106 BehaveEducator, 111 Grade, 113 BagrutGrade, 114 MagenGrade, 121 Maakav, 131 FormAnswer, 141 FormViewAnswer, 151 SchoolActivityAnswer, 171/181/191 staff export files, 201 ParentsConsentAnswer, 211 ParentsConsentSharedAccess, 221 TimeTable, 231 StudentPicture, 241 SchoolTest. The app's routes use `eventUserId` as the student and `eventKey` for the item. The app loads the newest seven when its main screen opens, with no timer. Only opening the list marks items read, through a separate `PUT`.

The opt-in notification refresh (`notifications.py`) reads this list every 5–60 minutes, never sends the `PUT`, and maps each new `eventType` to the data types it changes. Digests of the items it has seen leave out `readTime`, so reading an item in the app does not count as new.

Push (read from the app, not used by the integration): the app gets pushes through its own Firebase project with `@havesource/cordova-plugin-push` (channel `MashovPushNotifications`). It sends its FCM token as `registrationId` in the login body and via `PUT push/registrationId`; the website never registers. A push carries `additionalData: {semel, messageType, messageData}`. `messageType` is the bitmask `{behave:1, grade:2, email:4, bagrut:8, homework:128, maakav:256, timeTable:512, studentPicture:1024, schoolTest:2048, behaveTeacherPush:4096, debug:1<<30}`, and `messageData` holds only IDs (`studentGuid`, `lessonId`, `conversationId`, `gradingEventId`, `maakavId`, ...). The data must still be fetched. The push categories are `push/options` (GET/PUT, a number), which also appears as `pushOptions` in `user/settings`. `POST users/debug/push` sends a test push to the user's devices (a write).

`GET user/settings`:

```json
{ "detailsState": 0, "emailNotifications": true, "isDigitalApproved": [2025], "pushOptions": 0 }
```

`GET user/details`:

```json
{ "semel": "<SEMEL>", "userId": "<PARENT_GUID>", "detailsState": 0, "email": "<EMAIL>", "emailSet": "datetime", "emailVerified": "datetime",
  "cellphone": "<PHONE>", "cellphoneSet": "datetime", "cellphoneVerified": "datetime" }
```

`GET user/devices`:

```json
[{ "deviceId": 0, "semel": "<SEMEL>", "userId": "<GUID>", "appName": "string", "appVersion": "string", "appBuild": "string",
   "apiVersion": "string", "devicePlatform": "string", "deviceManufacturer": "string", "deviceModel": "string",
   "deviceVersion": "string", "addedTime": "datetime", "lastAuth": "datetime", "lastIp": "<IP>" }]
```

---

## 3. Answers to the questions

**Q1. Parent approvals, trips and forms.** There are two separate systems.
- **Trips and activities (the main one for HA).**
  - List: `GET schoolActivities/permitted`. Detail: `GET schoolActivities/<id>/permitted`. This parent's answers: `GET schoolActivities/<id>/userAnswers`.
  - Fields: title is `title`, description is `description` (HTML), activity dates are `activityStartDate`/`activityEndDate`, the due date is `endAnswerDate`, and the type is `activityType` (`1` trip, `4` סל תרבות).
  - Status: `isAnswered` on the list. Per child, `schoolActivityAnswer.answer` is `1` approved, `2` approved with health conditions, `3` denied, or missing for pending.
  - There is no explicit "rejected by school" state.
  - There are **no price or payment fields**.
  - Attachments: `schoolActivities/<id>/files/<fileId>/<fileName>`. The field holding the file list is **not verified**.
  - Submitting is `PUT students/<child>/schoolActivities/<id>` (writes).
- **Forms and consent questionnaires.**
  - List: `GET user/forms?isParentsConsent=true|false`. Detail: `GET forms/<formId>`. My answer: `GET forms/<formId>/answer`.
  - Fields: `formData` (JSON string with questions), `endTime` (due date), `isAnswered`.
  - Submitting is `PUT forms/<formId>/answer`.
  - These lists were empty for this account, so the field names come from the bundle.

**Q2. Mail attachments.**
- The inbox list gives only `hasAttachments` (boolean); file metadata is not included.
- File metadata (`files: [{fileId, fileName}]`) is in the message objects returned by `GET mail/conversations/<id>` or `GET mail/messages/<id>`. This comes from the bundle; it was not seen live.
- Download URL: `GET /api/mail/messages/<messageId>/files/<fileId>/download/<urlencoded fileName>`.
- Whether downloading changes read status is **not verified**. You can only get the `fileId` from the detail call, and that call itself is what likely marks the conversation read.

**Q3. Does `GET mail/conversations/{id}` mark the conversation read?**
- The web client **never calls `markAsRead` when opening a conversation**. It only calls `GET mail/conversations/<id>`. `PUT mail/conversations/markAsRead` (body: an array of conversation IDs) is used only by the bulk "mark as read" action.
- So any read-marking has to happen server-side on the GET. This is **inferred, not verified**: the account had no unread mail to test without breaking your rule.
- `GET mail/messages/<id>` also returns `body`. Whether it marks read is unknown.
- I found no endpoint that is documented to return bodies without marking read.
- **Suggested test:** send yourself a message from a second account. Read `mail/counts` (`unreadConversations`), call `GET mail/messages/<id>`, then read `mail/counts` again. If it doesn't mark read, it is the safe body endpoint. Do the same for the conversation endpoint. As a fallback you can call `PUT mail/conversations/markAsUnread` with `[id]` after fetching.

**Q4. Unread list.**
- `GET mail/unread/conversations?skip=&take=` lists unread conversations. It is the same as the folder list with folder `unread`, without bodies. The total is in `X-Conversations-Count`.
- `GET mail/counts?$select=unreadConversations` gives the count.
- The dashboard calls both on every load, and I saw no side effects. Since the unread count was already 0, a read-marking side effect could not have shown up, but it would be implausible for a list call.

**Q5. Calendar, exams and timetable changes.**
- Timetable changes and cancellations: `GET students/<child>/timetable/changes?start=&end=`.
- Base timetable: `GET students/<child>/timetable`, plus `GET bells`.
- Holidays: `GET holidays`.
- Exams and graded events with dates: `GET students/<child>/gradingEvents` (`gradingEvent.eDate`, `name`, `startLesson`/`endLesson`).
- The "לוח מבחנים ואירועים (שחף)" menu item opens an external Shahaf site whose URL comes from `GET shahaf/coolSite` (empty for this school).
- Parent-teacher meetings: `GET parents/<parent>/children/<child>/meetings`.
- Online lessons: `GET bbb?start=&end=`.
- I found no general "school calendar" endpoint in the parent bundle.

**Q6. Headers.**
- Session cookies (HttpOnly) on every call.
- `X-Csrf-Token` on every API call. Its value comes from the `X-Csrf-Token` response header of `POST login`.
- No `apiVersion` header; `apiVersion` goes in the login body.
- Optional: `devicePass` / `deviceBiometric` for mobile login only.

**Q7. Other endpoints the parent app uses:**
- Noticeboard: `students/<child>/messageBoard`.
- Behavior: `behave`, `outBehave`, `dailyBehave`, and the `achvas` dictionary.
- Lesson counts: `lessonsCount`.
- Groups and teachers: `groups`.
- Homework: `homework`.
- Follow-up notes: `maakav`, `parentMaakav/<id>/maakav`.
- Justification requests: `justificationrequests`.
- Early-release requests: `studentReleases`.
- Files: `files`, `studyFiles`, `reportCards`.
- Accommodations: `hatamot`, `bagrut/hatamot`.
- Individual lessons: `specialHoursLessons`.
- Moodle grades: `moodle/*/grades`.
- Online classes and recordings: `bbb`, `bbb/recordings`.
- Notifications: `user/notifications`.
- Settings and profile: `user/settings`, `user/details`, `user/devices`, `user/bindings`, `push/options`.
- Hebrew calendar: `hebrewDates`.
- **Automatic side effects to know about:**
  - `PUT consent` is fired on page load after login.
  - Opening the Notifications page or the bell list fires `PUT user/notifications/` (marks read).
  - The trip answer page may prompt for `PUT digitalApproval/<parent>`.

---

## 4. Not verified (bundle-only or inferred)

- **Mail**
  - The server marks read on `GET mail/conversations/<id>` (inferred from client behavior).
  - Read-status effect of `GET mail/messages/<id>` and of attachment downloads.
  - `message.files[]` shape (`fileId`, `fileName`) and the attachment download response (`Content-Type` / `Content-Disposition`). The mailbox had no attachments (re-checked 2026-11-17).
- **Forms:** `forms/<id>`, `forms/<id>/answer`, and the field names `formData`, `endTime`, `isAnswered`, `isMust`, `isMultipleAnswer`. The lists were empty (re-checked 2026-11-17).
- **Trips:** the `schoolActivities` attachment list field, `activityData` / `questions`, the `remark` field, and the exact body of `PUT students/<child>/schoolActivities/<id>`.
- **Empty lists:** item shapes for `timetable/changes` (`changes` only; `cancellations` is verified), `maakav` and its file URL, `parentMaakav/<id>/maakav`, `justificationrequests` (503), `studentReleases`, `files`, `studyFiles`, `reportCards`, `hatamot`, `grades`, `outBehave`, `dailyBehave`, `bbb/recordings`, and meetings.
- **Downloads:** whether file URLs require the `X-Csrf-Token` header or work with cookies alone.
- **Write endpoints:** every endpoint marked `writes`. None was called.
- **Mobile-app variant:** `meetings/parents/<parent>/meetings[/<child>]/details` (used when `IsDevice`).
