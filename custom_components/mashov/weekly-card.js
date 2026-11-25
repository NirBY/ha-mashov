/* Weekly school hours use each child's actual timetable, not every school bell. */
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const TEXT = {
  he: {title:"השבוע שלי",day:"יום",start:"מתחילים",end:"מסיימים",subjects:"מקצועות לפי סדר",none:"אין לימודים במערכת",missing:"בית הספר לא פרסם זמני צלצולים. מוצגים מספרי השיעורים.",unavailable:"המערכת אינה זמינה כרגע.",partial:"המערכת חלקית; שעות התחלה וסיום אינן מחושבות.",stale:"מוצג המידע האחרון שנשמר; ממתין לרענון.",source:"לפי המערכת שפורסמה במשוב. שינויים מתעדכנים ברענון המקור; ביטולים שפורסמו רק בהודעות אינם משנים את השעות כאן.",sourceCancellations:"לפי המערכת וביטולי השיעורים שפורסמו במשוב. ביטול של השיעור הראשון או האחרון מעדכן את שעות ההתחלה והסיום בימים הקרובים; ביטולים שפורסמו רק בהודעות אינם נכללים.",notOffered:"בית הספר אינו מפרסם ביטולי שיעורים במשוב, ולכן השעות לפי המערכת הקבועה.",cancellationsUnavailable:"לא ניתן לטעון כרגע את ביטולי השיעורים. ייתכן שביטולים חסרים או אינם עדכניים.",cancelled:"בוטל",laterStart:"התחלה מאוחרת בגלל ביטול",earlierEnd:"סיום מוקדם בגלל ביטול",allCancelled:"כל השיעורים ביום זה בוטלו",updated:"עודכן",previous:"השבוע הקודם",next:"השבוע הבא",today:"השבוע",lesson:"שיעור",variable:"יש שיעורים המוגבלים לשבועות מסוימים. יש לאמת את השעות מול בית הספר."},
  en: {title:"My school week",day:"Day",start:"Starts",end:"Ends",subjects:"Subjects in order",none:"No scheduled lessons",missing:"The school has not published bell times. Lesson numbers are shown.",unavailable:"The timetable is unavailable.",partial:"The timetable is incomplete; start and end times are not calculated.",stale:"Showing saved data while the source refreshes.",source:"From the timetable published in Mashov. Source refreshes update this view; cancellations published only in messages do not change these times.",sourceCancellations:"From the timetable and lesson cancellations published in Mashov. A cancelled first or last lesson moves upcoming start and end times; cancellations published only in messages are not included.",notOffered:"This school does not publish lesson cancellations in Mashov, so hours follow the regular timetable.",cancellationsUnavailable:"Lesson cancellations could not be loaded. Cancellations may be missing or out of date.",cancelled:"Cancelled",laterStart:"Later start: cancellation",earlierEnd:"Earlier end: cancellation",allCancelled:"All lessons on this day are cancelled",updated:"Updated",previous:"Previous week",next:"Next week",today:"This week",lesson:"Lesson",variable:"Some lessons apply to specific weeks. Confirm hours with the school."}
};

export function dateInZone(now, zone) {
  return new Intl.DateTimeFormat("en-CA", {timeZone: zone, year:"numeric",month:"2-digit",day:"2-digit"}).format(now);
}
const addDays = (date, n) => new Date(Date.parse(date + "T12:00:00Z") + n * 86400000).toISOString().slice(0,10);
const time = value => /^([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(value || "") ? value.slice(0,5) : "";

export function schoolDays(week) {
  return week.filter(day => day.lessons.length > 0 && !day.holiday);
}

/* A lesson slot is cancelled on a date only when every group in it is cancelled then. Only
   upcoming dates (today or later) skip cancelled slots at the start or end of the day, so hours
   move only for an upcoming cancellation of the first or last lesson. Past days keep the
   published hours and only mark the cancelled lessons. */
export function schoolWeek(schedule, bells, holidays, today, offset = 0, complete = true) {
  const sunday = addDays(today, -new Date(today + "T12:00:00Z").getUTCDay() + offset * 7);
  const slots = new Map((bells || []).map(x => [Number(x.lessonNumber), {start:time(x.startTime),end:time(x.endTime)}]));
  return Array.from({length:7}, (_, i) => {
    const date = addDays(sunday, i);
    const holiday = (holidays || []).find(x => String(x.start || "").slice(0,10) <= date && String(x.end || "").slice(0,10) >= date);
    const lessons = (schedule || []).filter(x => Number(x.day) === i + 1).flatMap(x => x.lessons || [])
      .map(x => ({...x, cancelled: Array.isArray(x.cancelled) && x.cancelled.includes(date)})).sort((a,b) => a.lesson - b.lesson);
    const groups = [...new Set(lessons.map(x => Number(x.lesson)))].map(n => lessons.filter(x => Number(x.lesson) === n));
    const upcoming = date >= today, gone = group => upcoming && group.every(x => x.cancelled);
    let lo = 0, hi = groups.length - 1;
    while (lo <= hi && gone(groups[lo])) lo++;
    while (hi >= lo && gone(groups[hi])) hi--;
    const kept = lo <= hi, first = kept ? groups[lo] : undefined, last = kept ? groups[hi] : undefined;
    const open = !holiday && complete;
    const definite = group => !!group && group.some(x => x.weeks == null);
    const variable = lessons.some(x => x.weeks != null);
    return {date,day:i + 1,holiday:holiday?.name || (holiday ? "—" : ""),lessons,
      start: open && definite(first) ? slots.get(Number(first[0].lesson))?.start || "" : "",
      end: open && definite(last) ? slots.get(Number(last[0].lesson))?.end || "" : "",
      laterStart: open && lo > 0 && lo <= hi,
      earlierEnd: open && hi < groups.length - 1 && lo <= hi,
      allCancelled: open && groups.length > 0 && lo > hi,
      variable};
  });
}

export class MashovWeeklyCard extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode:"open"}); this._offset = 0;
    this.shadowRoot.addEventListener("click", event => {
      const button = event.target.closest("button[data-week]");
      if (!button) return;
      this._offset = button.dataset.week === "0" ? 0 : this._offset + Number(button.dataset.week);
      this._render();
    });
  }
  setConfig(config) {
    if (!/^sensor\.[a-z0-9_]+$/.test(config.entity || "")) throw new Error("Choose a Mashov timetable sensor");
    this._config = {...config, accent:/^#[0-9a-f]{6}$/i.test(config.accent || "") ? config.accent : "#5adcf0"}; this._render();
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const states = [hass.states[this._config.entity],hass.states[this._config.bells_entity],hass.states[this._config.holidays_entity]];
    const today = dateInZone(new Date(), hass.config?.time_zone || "Asia/Jerusalem");
    if (today !== this._today || states.some((state,i) => state !== this._states?.[i])) {
      this._states = states; this._today = today; this._render();
    }
  }
  _render() {
    if (!this._config || !this._hass || !this._states) return;
    const he = this._config.language !== "en", t = TEXT[he ? "he" : "en"];
    const [state,bells,holidays] = this._states;
    const available = s => s && !["unknown","unavailable"].includes(s.state);
    const a = state?.attributes || {};
    const complete = a.weekly_schedule_complete === true;
    const week = schoolWeek(a.weekly_schedule || [], available(bells) ? bells.attributes.items : [], available(holidays) ? holidays.attributes.items : [], this._today, this._offset, complete);
    const rows = schoolDays(week);
    const date = d => new Intl.DateTimeFormat(he ? "he-IL" : "en-GB",{day:"numeric",month:"numeric",timeZone:"UTC"}).format(new Date(d + "T12:00:00Z"));
    const dayName = d => new Intl.DateTimeFormat(he ? "he-IL" : "en-GB",{weekday:"short",timeZone:"UTC"}).format(new Date(d + "T12:00:00Z"));
    const notices = [];
    if (!available(state)) notices.push(t.unavailable);
    else if (!complete) notices.push(t.partial);
    else if (!rows.length) notices.push(t.none);
    if (this._states.some(s => s?.attributes.data_stale) || (this._config.bells_entity && !available(bells)) || (this._config.holidays_entity && !available(holidays))) notices.push(t.stale);
    if (!available(bells) || !bells.attributes.items?.length) notices.push(t.missing);
    if (rows.some(row => row.variable)) notices.push(t.variable);
    const cancellations = a.cancellations_status;
    if (cancellations && !["ok","not_offered"].includes(cancellations)) notices.push(t.cancellationsUnavailable);
    const note = cancellations === "not_offered" ? t.notOffered : cancellations ? t.sourceCancellations : t.source;
    this.shadowRoot.innerHTML = `<style>
      :host{display:block}*{box-sizing:border-box}ha-card{display:block;background:linear-gradient(145deg,#141e32,#0c1424);color:#f1f5ff;border:1px solid ${this._config.accent}66;border-radius:22px;box-shadow:0 0 18px ${this._config.accent}18;padding:18px 14px;overflow:hidden;font:14px/1.6 var(--paper-font-body1_-_font-family,Arial,sans-serif)}h2{color:${this._config.accent};font-size:20px;margin:0 0 2px}.range{color:#bbcadf;font-size:12px}.nav{display:flex;gap:6px;margin:12px 0}button{flex:1;border:1px solid #ffffff25;border-radius:10px;background:#ffffff08;color:#e8f0ff;font:inherit;font-size:12px;padding:7px 3px;cursor:pointer}button:focus-visible{outline:2px solid ${this._config.accent}}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{text-align:start;vertical-align:top;border-bottom:1px solid #ffffff12;padding:10px 3px}th{color:#bdcde0;font-size:11px;font-weight:400}th:first-child{width:15%}th.time{width:17%}td.time{font-size:15px;color:${this._config.accent};font-weight:700;white-space:nowrap}small{display:block;color:#bbcadf;font-size:10px;font-weight:400}tr.today{background:${this._config.accent}0d}.lesson{display:block;overflow-wrap:anywhere;line-height:1.5;margin-bottom:5px}.number{color:${this._config.accent};font-size:11px}.note{font-size:11px;color:#bdcde0;margin:12px 0 0}.notice{border-inline-start:2px solid ${this._config.accent};padding-inline-start:9px;color:#d3dfef;font-size:12px;margin:10px 0}.holiday{color:#bedcc8}.lesson.cancelled .name{text-decoration:line-through;color:#97a6bd}.tag{display:inline-block;border:1px solid #ffb4a8;color:#ffcdc4;border-radius:6px;font-size:10px;line-height:1.4;padding:0 5px;margin-inline-start:6px}small.moved{color:#ffcdc4}@media(min-width:600px){ha-card{padding:20px}th:first-child{width:13%}th.time{width:14%}.lesson{display:inline-block;margin-inline-end:14px}.lesson+.lesson::before{content:' · ';color:#879ab7;margin-inline-end:8px}}
    </style><ha-card dir="${he ? "rtl":"ltr"}"><h2>◷ ${esc(this._config.title || t.title)}</h2><div class="range">${date(week[0].date)} – ${date(week[6].date)}</div><div class="nav"><button data-week="-1" aria-label="${t.previous}">${t.previous}</button><button data-week="0">${t.today}</button><button data-week="1" aria-label="${t.next}">${t.next}</button></div>${notices.map(n=>`<p class="notice" role="status">${esc(n)}</p>`).join("")}${available(state) && rows.length ? `<table><thead><tr><th>${t.day}</th><th class="time">${t.start}</th><th class="time">${t.end}</th><th>${t.subjects}</th></tr></thead><tbody>${rows.map(row=>`<tr class="${row.date===this._today ? "today":""}"><td><strong>${dayName(row.date)}</strong><small>${date(row.date)}</small></td><td class="time"><bdi>${row.start || "—"}</bdi>${row.laterStart ? `<small class="moved">${t.laterStart}</small>` : ""}</td><td class="time"><bdi>${row.end || "—"}</bdi>${row.earlierEnd ? `<small class="moved">${t.earlierEnd}</small>` : ""}</td><td>${row.holiday ? `<span class="holiday">${esc(row.holiday)}</span>` : row.lessons.length ? (row.allCancelled ? `<small class="moved">${t.allCancelled}</small>` : "") + row.lessons.map(x=>`<span class="lesson${x.cancelled ? " cancelled" : ""}"><span class="number">${x.lesson}.</span> <span class="name">${esc(x.subject)}</span>${x.weeks != null ? " *" : ""}${x.cancelled ? `<span class="tag">${t.cancelled}</span>` : ""}${x.room ? `<small>${esc(x.room)}</small>`:""}</span>`).join("") : `<small>${complete ? t.none : "—"}</small>`}</td></tr>`).join("")}</tbody></table>`:""}<p class="note">${esc(note)}</p>${a.last_update ? `<small>${t.updated}: ${esc(new Intl.DateTimeFormat(he?"he-IL":"en-GB",{dateStyle:"short",timeStyle:"short",timeZone:this._hass.config?.time_zone || "Asia/Jerusalem"}).format(new Date(a.last_update)))}</small>`:""}</ha-card>`;
  }
  getCardSize(){return 10;}
  getGridOptions(){return {columns:12,rows:"auto",min_columns:6};}
}
if (!customElements.get("mashov-weekly-card")) customElements.define("mashov-weekly-card", MashovWeeklyCard);
if (typeof window !== "undefined") {
  window.customCards = window.customCards || [];
  if (!window.customCards.some(card => card.type === "mashov-weekly-card")) window.customCards.push({type:"mashov-weekly-card",name:"Mashov school week",description:"Weekly subjects and each child's start/end times"});
}
