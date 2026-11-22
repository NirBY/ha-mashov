/* Mashov homework: completion stays in HA's todo entity, never in browser storage. */
const TEXT = {
  he: { title: "שיעורי בית", days: "ימי דיווח", tasks: "משימות", open: "פתוחות", empty: "אין שיעורי בית בחלון הדיווח הנוכחי", loading: "טוען שיעורי בית…", unavailable: "שיעורי הבית אינם זמינים כרגע. נסו שוב אחרי הרענון.", stale: "מוצג המידע האחרון שנשמר; מקור שיעורי הבית ממתין לרענון.", failed: "לא ניתן לשמור את הסימון. המשימה נשארה במצבה הקודם.", retry: "נסה שוב", older: "הצג ימים ישנים יותר", recent: "חזרה לימים האחרונים", undated: "ללא תאריך דיווח", hint: "סימון משימה משאיר אותה ברשימה עם קו חוצה. אפשר לבטל את הסימון." },
  en: { title: "Homework", days: "homework days", tasks: "tasks", open: "open", empty: "No homework in the current reporting window", loading: "Loading homework…", unavailable: "Homework is unavailable. Try again after refreshing.", stale: "Showing saved homework while the school source refreshes.", failed: "Could not save the checkmark. The task kept its previous status.", retry: "Try again", older: "Show older days", recent: "Back to recent days", undated: "No reported date", hint: "Checked tasks stay in the list with a strike-through. Uncheck to reopen." },
};

export function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export function reportedDate(item) {
  // Mashov todo descriptions start with the lesson date; this is not a due date.
  const value = /^(\d{4}-\d{2}-\d{2})(?: · |$)/.exec(item.description || "")?.[1];
  if (!value) return "";
  const date = new Date(`${value}T12:00:00Z`);
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value ? value : "";
}

export function groupHomework(items, days = 3, showOlder = false) {
  const groups = new Map();
  const seen = new Set();
  for (const item of items) {
    if (!item.uid || seen.has(item.uid)) continue;
    seen.add(item.uid);
    const date = reportedDate(item);
    if (!groups.has(date)) groups.set(date, []);
    groups.get(date).push(item);
  }
  const dates = [...groups.keys()].filter(Boolean).sort().reverse();
  const selected = showOlder ? dates : dates.slice(0, days);
  // Undated assignments remain visible, rather than silently disappearing.
  if (groups.has("")) selected.push("");
  return {
    olderDays: Math.max(0, dates.length - days),
    totalDays: dates.length,
    groups: selected.map(date => ({ date, items: groups.get(date).slice().sort((a, b) => String(a.summary).localeCompare(String(b.summary), "he") || a.uid.localeCompare(b.uid)) })),
  };
}

export async function readHomework(hass, entity) {
  const result = await hass.callWS({ type: "call_service", domain: "todo", service: "get_items", service_data: { entity_id: entity }, return_response: true });
  const items = result?.response?.[entity]?.items;
  if (!Array.isArray(items)) throw new Error("Invalid homework response");
  return items;
}

export function setHomeworkCompleted(hass, entity, uid, completed) {
  return hass.callService("todo", "update_item", { item: uid, status: completed ? "completed" : "needs_action" }, { entity_id: entity }, false);
}

export class MashovHomeworkCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._items = [];
    this._busy = new Set();
    this._request = 0;
    this._showOlder = false;
    this.shadowRoot.addEventListener("change", event => {
      const input = event.target;
      if (input.matches("input[data-uid]")) this._toggle(input.dataset.uid, input.checked);
    });
    this.shadowRoot.addEventListener("click", event => {
      if (event.target.closest("[data-older]")) {
        this._showOlder = !this._showOlder;
        this._render();
      } else if (event.target.closest("[data-retry]")) this._load();
    });
    this.shadowRoot.addEventListener("toggle", event => {
      if (event.target.matches("details")) this._open = event.target.open;
    }, true);
  }

  setConfig(config) {
    if (!/^todo\.[a-z0-9_]+$/.test(config.entity || "")) throw new Error("Choose a Mashov todo entity");
    const days = config.days ?? 3;
    if (!Number.isInteger(days) || days < 1 || days > 14) throw new Error("days must be between 1 and 14");
    if (this._config?.entity !== config.entity) {
      this._request++;
      this._items = [];
      this._loaded = false;
      this._lastState = undefined;
      this._showOlder = false;
      this._busy.clear();
    }
    this._config = { ...config, days, accent: /^#[0-9a-f]{6}$/i.test(config.accent || "") ? config.accent : "#5adcf0" };
    this._open = this._open ?? !(config.collapsed ?? true);
    this._render();
    if (this._hass) this.hass = this._hass;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const state = hass.states[this._config.entity];
    const source = hass.states[this._config.source_entity];
    const changed = state !== this._lastState || source !== this._lastSource;
    this._lastState = state;
    this._lastSource = source;
    this._available = !!state && !["unavailable", "unknown"].includes(state.state);
    if (!this._available) {
      this._request++;
      this._render();
    } else if (changed || !this._loaded) this._load();
  }

  connectedCallback() {
    if (this._hass && this._config) this.hass = this._hass;
  }

  disconnectedCallback() {
    this._request++;
  }

  async _load() {
    if (!this._available || !this._config) return;
    if (this._loading || this._busy.size) { this._queued = true; return; }
    this._loading = true;
    this._queued = false;
    const request = ++this._request;
    const entity = this._config.entity;
    this._render();
    try {
      const items = await readHomework(this._hass, entity);
      if (request !== this._request || entity !== this._config.entity) return;
      this._items = items;
      this._loaded = true;
      this._error = "";
    } catch (_) {
      if (request === this._request) this._error = "unavailable";
    } finally {
      this._loading = false;
      this._render();
      if (this._queued) this._load();
    }
  }

  async _toggle(uid, completed) {
    if (!this._available || this._busy.has(uid) || !this._items.some(item => item.uid === uid)) return;
    const entity = this._config.entity;
    this._request++; // Ignore reads that began before this completion change.
    this._busy.add(uid);
    this._render();
    try {
      await setHomeworkCompleted(this._hass, entity, uid, completed);
      if (entity !== this._config.entity) return;
      this._items = this._items.map(item => item.uid === uid ? { ...item, status: completed ? "completed" : "needs_action" } : item);
      this._error = "";
    } catch (_) {
      if (entity === this._config.entity) this._error = "failed";
    } finally {
      if (entity === this._config.entity) {
        this._busy.delete(uid);
        this._render();
        if (!this._error) this._load();
      }
    }
  }

  _render() {
    if (!this._config) return;
    const t = TEXT[this._config.language === "en" ? "en" : "he"];
    const he = t === TEXT.he;
    const grouped = groupHomework(this._items, this._config.days, this._showOlder);
    const visible = grouped.groups.flatMap(group => group.items);
    const remaining = visible.filter(item => item.status !== "completed").length;
    const active = this.shadowRoot.activeElement;
    const focusedUid = active?.dataset?.uid;
    const focusOlder = active?.hasAttribute("data-older");
    const dateLabel = date => date ? new Intl.DateTimeFormat(he ? "he-IL" : "en-GB", { weekday: "long", day: "numeric", month: "numeric", timeZone: "UTC" }).format(new Date(`${date}T12:00:00Z`)) : t.undated;
    const message = !this._available ? "unavailable" : this._error || (!this._loaded ? "loading" : "");
    const stale = this._lastState?.attributes?.data_stale;
    const content = grouped.groups.map(group => `<section><h3>${escapeHTML(dateLabel(group.date))}</h3>${group.items.map(item => {
      const done = item.status === "completed";
      const description = (item.description || "").replace(/^\d{4}-\d{2}-\d{2}(?: · )?/, "");
      return `<label class="task ${done ? "completed" : ""}"><input type="checkbox" data-uid="${escapeHTML(item.uid)}" ${done ? "checked" : ""} ${!this._available || this._busy.has(item.uid) ? "disabled" : ""}><span class="task-text"><span>${escapeHTML(item.summary)}</span>${description ? `<small>${escapeHTML(description)}</small>` : ""}</span></label>`;
    }).join("")}</section>`).join("");
    this.shadowRoot.innerHTML = `<style>
      :host{display:block}*{box-sizing:border-box}ha-card{display:block;--accent:${this._config.accent};background:linear-gradient(145deg,#141e32,#0c1424);color:#f1f5ff;border:1px solid var(--accent);border-radius:22px;box-shadow:0 0 18px ${this._config.accent}20;overflow:hidden;font-size:15px;line-height:1.6}
      summary{cursor:pointer;padding:18px 20px;min-height:64px;color:var(--accent);font-weight:700}summary:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}summary small{display:block;color:#c1cde0;font-size:12px;font-weight:400;padding-inline-start:18px}
      .body{padding:0 18px 18px}section+section{border-top:1px solid #ffffff22;margin-top:14px}h3{font-size:14px;color:var(--accent);margin:12px 0 6px}.task{display:flex;align-items:flex-start;gap:12px;padding:12px 4px;cursor:pointer;border-bottom:1px solid #ffffff0b;overflow-wrap:anywhere}.task input{flex:0 0 auto;width:21px;height:21px;margin:3px 0 0;accent-color:var(--accent);cursor:pointer}.task-text{min-width:0;white-space:pre-wrap}.task-text small{display:block;color:#b8c8dd;font-size:12px}.completed .task-text{text-decoration:line-through;color:#acbbcf}.task:has(input:disabled){cursor:wait}button{font:inherit;color:var(--accent);background:#ffffff08;border:1px solid #ffffff30;border-radius:12px;padding:10px 16px;cursor:pointer;margin-top:14px;width:100%}.notice{border:1px solid #ffffff28;border-radius:12px;padding:10px 12px;margin:4px 0 10px}.hint{font-size:12px;color:#b8c8dd;margin:8px 0 0}@media(max-width:400px){ha-card{font-size:14px}.body{padding-inline:12px}}
    </style><ha-card dir="${he ? "rtl" : "ltr"}"><details ${this._open ? "open" : ""}><summary>${escapeHTML(this._config.title || t.title)}<small>${this._loaded ? `${grouped.groups.filter(g => g.date).length} ${t.days} · ${visible.length} ${t.tasks} · ${remaining} ${t.open}` : escapeHTML(t.loading)}</small></summary><div class="body">${message ? `<p class="notice" role="status">${escapeHTML(t[message])}</p>` : ""}${stale ? `<p class="notice">${escapeHTML(t.stale)}</p>` : ""}${this._loaded && !visible.length && !message ? `<p>${escapeHTML(t.empty)}</p>` : ""}${content}${grouped.olderDays ? `<button type="button" data-older aria-expanded="${this._showOlder}">${escapeHTML(this._showOlder ? t.recent : `${t.older} (${grouped.olderDays})`)}</button>` : ""}${this._error ? `<button type="button" data-retry>${escapeHTML(t.retry)}</button>` : ""}<p class="hint">${escapeHTML(t.hint)}</p></div></details></ha-card>`;
    if (focusedUid) [...this.shadowRoot.querySelectorAll("input[data-uid]")].find(input => input.dataset.uid === focusedUid)?.focus();
    else if (focusOlder) this.shadowRoot.querySelector("[data-older]")?.focus();
  }

  getCardSize() { return this._open ? 6 : 1; }
  getGridOptions() { return { columns: 12, rows: "auto", min_columns: 6 }; }
  static getStubConfig() { return { entity: "", days: 3, collapsed: true }; }
}

if (!customElements.get("mashov-homework-card")) customElements.define("mashov-homework-card", MashovHomeworkCard);
if (typeof window !== "undefined") {
  window.customCards = window.customCards || [];
  if (!window.customCards.some(card => card.type === "mashov-homework-card")) window.customCards.push({ type: "mashov-homework-card", name: "Mashov homework", description: "Recent homework days, persistent checkboxes and older assignments" });
}
