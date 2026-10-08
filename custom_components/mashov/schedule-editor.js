/* Mashov's standalone editor uses HA's authenticated connection and theme. */
const TEXT = {
  ar: {loading:'جار التحميل…',error:'تعذر تحميل الجداول أو حفظها.'},
  ru: {loading:'Загрузка…',error:'Не удалось загрузить или сохранить расписания.'},
  uk: {loading:'Завантаження…',error:'Не вдалося завантажити або зберегти розклади.'},
  en: {title:'Refresh schedules', hub:'Hub', data:'Data type', general:'General — default schedule', mode:'Schedule type', daily:'Daily', weekly:'Weekly', interval:'Interval', clock:'Refresh time', days:'Weekdays', minutes:'Interval minutes', inherit:'Use General schedule', submit:'Submit', saved:'All schedules saved.', draft:'Unsaved changes', clean:'No unsaved changes', summary:'All schedules', help:'Select General to edit the default. Choose a data type to set its own schedule, or keep Use General checked. Switch between types freely; Submit saves all changes together.', disabled:'Disabled — no requests', shared:'General', custom:'Custom', timezone:'Timezone', yaml:'YAML overrides the General schedule. Custom data schedules remain independent.', changed:'Settings changed elsewhere. Reload before saving; your draft is still here.', invalid:'Check time, interval (5–1440 minutes) and weekly days for every edited type.', loading:'Loading…', reset:'Discard draft', error:'Could not load or save schedules.', back:'Back to integration'},
  he: {title:'תזמוני רענון', hub:'חשבון', data:'סוג מידע', general:'כללי — תזמון ברירת מחדל', mode:'סוג תזמון', daily:'יומי', weekly:'שבועי', interval:'מרווח קבוע', clock:'שעת רענון', days:'ימים בשבוע', minutes:'מרווח בדקות', inherit:'השתמש בתזמון הכללי', submit:'שמירה', saved:'כל התזמונים נשמרו.', draft:'שינויים שטרם נשמרו', clean:'אין שינויים לשמירה', summary:'כל התזמונים', help:'בחרו כללי לעריכת ברירת המחדל. בחרו סוג מידע להגדרת תזמון אישי, או השאירו שימוש בתזמון הכללי. אפשר לעבור בין הסוגים בחופשיות; שמירה שומרת את כל השינויים יחד.', disabled:'כבוי — ללא בקשות', shared:'כללי', custom:'אישי', timezone:'אזור זמן', yaml:'הגדרות YAML גוברות על התזמון הכללי. תזמונים אישיים נשארים עצמאיים.', changed:'ההגדרות השתנו במקום אחר. טענו מחדש לפני שמירה; הטיוטה עדיין כאן.', invalid:'בדקו שעה, מרווח (5–1440 דקות) וימי שבוע בכל סוג מידע שנערך.', loading:'טוען…', reset:'ביטול הטיוטה', error:'לא ניתן לטעון או לשמור תזמונים.', back:'חזרה לאינטגרציה'},
};
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const SCHEDULE_DRAFTS=new Map();
const SHARED_DATA=new Set(['holidays','mailbox']);
const clone = value => JSON.parse(JSON.stringify(value));

class MashovScheduleEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:'open'}); this.key='general'; this.message=''; this.busy=false; }
  set hass(value) { const previous=this.language; this._hass=value;this.language=value.locale?.language||'en'; if(this.isConnected && !this.started) this.load();else if(this.payload && previous!==this.language) this.translate(); }
  get hass() { return this._hass; }
  connectedCallback() { if(this.hass && !this.started) this.load();if(this.leave)window.addEventListener('beforeunload',this.leave); }
  disconnectedCallback() { window.removeEventListener('beforeunload',this.leave);if(!this.embedded&&!this.newHub&&this.payload)for(const entry of this.payload.entries){if(JSON.stringify(this.drafts[entry.entry_id])!==JSON.stringify(this.baseline(entry)))SCHEDULE_DRAFTS.set(this.cacheKey(entry.entry_id),{draft:clone(this.drafts[entry.entry_id]),baseline:clone(this.baseline(entry)),revision:entry.revision});} }
  cacheKey(id){return (this.hass?.user?.id||'')+':'+id;}
  get t() { return {...TEXT.en,...TEXT[this.language?.split('-')[0]],...this.payload?.ui}; }
  get entry() { return this.payload?.entries.find(e=>e.entry_id===this.entryId); }
  get draft() { return this.drafts[this.entryId]; }
  baseline(entry=this.entry) {return {general:entry.general,overrides:entry.overrides,student_schedules:entry.student_schedules||{}};}
  target(create=false) {if(!this.studentId) return this.draft; if(create) this.draft.student_schedules[this.studentId]||={overrides:{}}; return this.draft.student_schedules[this.studentId]||{overrides:{}};}
  get datasets() {return this.payload.datasets.filter(d=>!this.studentId || !SHARED_DATA.has(d.key));}
  get dirty() { return this.entry && ((this.newHub && (this.entry.enabled.length>0 || Object.values(this.accountDraft).some(Boolean))) || JSON.stringify(this.draft)!==JSON.stringify(this.baseline())); }
  async load() {
    this.started=true; this.shadowRoot.textContent=this.t.loading;
    try {
      this.payload=await this.hass.callWS({type:'mashov/schedules/get',language:this.language.split('-')[0]});
      this.newHub=!this.embedded && new URLSearchParams(location.search).get('new')==='1';
      if(this.embedded && this.inlineConfig?.setup) this.payload.entries=[{entry_id:'setup',title:'',general:clone(this.payload.default_general),overrides:{},student_schedules:{},enabled:[]}];
      if(this.newHub) {
        this.accountDraft={username:'',password:'',school_name:''};
        this.payload.entries=[{entry_id:'new',title:this.t.registerTitle,revision:'',general:clone(this.payload.default_general),overrides:{},enabled:[]}];
      }
      this.drafts=Object.fromEntries(this.payload.entries.map(e=>[e.entry_id,clone(this.baseline(e))]));
      if(!this.embedded&&!this.newHub)for(const entry of this.payload.entries){const cached=SCHEDULE_DRAFTS.get(this.cacheKey(entry.entry_id));if(cached){this.drafts[entry.entry_id]=clone(cached.draft);if(cached.revision!==entry.revision)this.message='changed';Object.assign(entry,cached.baseline);entry.revision=cached.revision;}}
      const selected=this.embedded?this.inlineConfig?.entry_id:new URLSearchParams(location.search).get('config_entry');
      this.entryId=this.payload.entries.some(e=>e.entry_id===selected)?selected:this.payload.entries[0]?.entry_id;
      this.leave=event=>{ if(this.dirty || Object.keys(this.drafts).some(id=>JSON.stringify(this.drafts[id])!==JSON.stringify(this.baseline(this.payload.entries.find(e=>e.entry_id===id))))) {event.preventDefault(); event.returnValue='';} };
      if(this.embedded && this._value) this.drafts[this.entryId]=clone(this._value);
      this.studentId=this.entry?.students?.[0]?.id||''; window.addEventListener('beforeunload',this.leave); this.render();
    } catch { this.shadowRoot.textContent=this.t.error; this.started=false; }
  }
  async translate() {
    const language=this.language;
    try {
      const metadata=await this.hass.callWS({type:'mashov/schedules/get',language:language.split('-')[0]});
      if(this.language!==language) return;
      this.payload.ui=metadata.ui;this.payload.errors=metadata.errors;this.payload.datasets=metadata.datasets;
      this.render();
    } catch { /* Preserve the current draft and its labels if translations cannot load. */ }
  }
  effective(key) {
    const target=this.target();
    if(key!=='general' && target.overrides[key]) return target.overrides[key];
    if(this.studentId && target.general) return target.general;
    if(key!=='general' && this.draft.overrides[key]) return this.draft.overrides[key];
    return {...this.draft.general,...this.payload.yaml_schedule};
  }
  current() {const target=this.target();return this.key==='general'?target.general:target.overrides[this.key];}
  describe(key) {
    const s=this.effective(key); let text=this.t[s.schedule_type];
    text+=' · '+(s.schedule_type==='interval'?s.schedule_interval+' '+this.t.minuteUnit:s.schedule_time);
    if(s.schedule_type==='weekly') text+=' · '+s.schedule_days.map(d=>this.day(d)).join(', ');
    if(key!=='general') text+=' · '+(this.target().overrides[key]?this.t.custom:this.t.shared)+(this.embedded||this.entry.enabled.includes(key)?'':' · '+this.t.disabled);
    return text;
  }
  day(day) { return new Intl.DateTimeFormat(this.hass.locale.language,{weekday:'short',timeZone:'UTC'}).format(new Date(Date.UTC(2024,0,1+Number(day)))); }
  render() {
    const t=this.t; if(!this.entry) { this.shadowRoot.textContent=t.error; return; }
    const dir=/^(he|ar)(-|$)/.test(this.language)?'rtl':'ltr';
    this.shadowRoot.innerHTML=`<style>
      :host{display:block;height:100%;overflow:auto;color:var(--primary-text-color);background:var(--primary-background-color);font-family:var(--ha-font-family,Arial)}
      *{box-sizing:border-box} main{max-width:900px;margin:auto;padding:24px} header{display:flex;align-items:center;gap:16px;margin-bottom:20px}h1{font-size:24px;margin:0}h2{font-size:19px;margin:0}a{color:var(--primary-color)} input[type=text],input[type=password]{width:100%;border:1px solid var(--divider-color);border-radius:8px;padding:12px;font:inherit;color:inherit;background:var(--secondary-background-color)}.datasets{display:grid;grid-template-columns:1fr 1fr;gap:12px}.datasets label{display:flex;align-items:center;gap:8px}.account-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
      section,details{background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:12px;padding:20px;margin:16px 0} .grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}label{display:block;font-size:14px;margin-bottom:6px} select,input[type=time],input[type=number]{width:100%;border:1px solid var(--divider-color);border-radius:8px;padding:12px;font:inherit;color:inherit;background:var(--secondary-background-color)}
      .row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:16px 0}.row label{margin:0}.days{display:flex;gap:8px;flex-wrap:wrap}.days label{padding:8px;border:1px solid var(--divider-color);border-radius:8px;display:flex;gap:6px;align-items:center}
      button{cursor:pointer;border:1px solid var(--divider-color);border-radius:8px;padding:11px 18px;font:inherit;background:var(--card-background-color);color:inherit}button.primary{background:var(--primary-color);color:var(--text-primary-color,#fff);border:0}button:disabled{opacity:.55;cursor:default}.info{border-radius:50%;padding:2px 8px;font-weight:bold;font-size:14px} .muted{color:var(--secondary-text-color);font-size:14px} .status{min-height:24px;margin:8px 0}.error{color:var(--error-color)} summary{cursor:pointer;font-weight:500}table{width:100%;border-collapse:collapse;margin-top:14px;font-size:14px}td,th{text-align:start;border-bottom:1px solid var(--divider-color);padding:9px}.scroll{overflow-x:auto}footer{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:20px 0}
      @media(max-width:600px){main{padding:12px}.grid,.account-grid,.datasets{grid-template-columns:1fr}section,details{padding:16px}}
      main.embedded{padding:0;max-width:none}.embedded>header,.embedded>footer{display:none}.embedded section{margin:0;padding:12px}.embedded>label[for=hub],.embedded>#hub{display:none}:host([embedded]){height:auto;overflow:visible}
    </style><main dir="${dir}" class="${this.embedded?'embedded':''}"><header><a href="/config/integrations/integration/mashov">${escape(t.back)}</a><h1>Mashov</h1></header>
      ${this.newHub?`<h2>${escape(t.registerTitle)}</h2><section><h2>${escape(t.account)}</h2><div class="account-grid">${['username','password','school_name'].map(field=>`<div><label for="${field}">${escape(t[field])}</label><input id="${field}" type="${field==='password'?'password':'text'}" required autocomplete="${field==='password'?'new-password':'off'}" value="${escape(this.accountDraft[field])}"></div>`).join('')}</div><p class="muted">${escape(t.choose_school_id)}</p></section><details><summary>${escape(t.selectData)}</summary><div class="datasets">${this.payload.datasets.map(d=>`<label><input type="checkbox" data-source="${escape(d.key)}" ${this.entry.enabled.includes(d.key)?'checked':''}>${escape(d.label)}</label>`).join('')}</div></details>`:`<label for="hub">${escape(t.hub)}</label><select id="hub">${this.payload.entries.map(e=>`<option value="${escape(e.entry_id)}" ${e.entry_id===this.entryId?'selected':''}>${escape(e.title)}</option>`).join('')}</select>`}
      ${!this.newHub?`<label for="student">${escape(t.student)}</label><select id="student">${(this.entry.students||[]).map(st=>`<option value="${escape(st.id)}" ${this.studentId===st.id?'selected':''}>${escape(st.name)}</option>`).join('')}<option value="" ${!this.studentId?'selected':''}>${escape(t.accountSchedules)}</option></select><p class="muted">${escape(this.studentId?t.studentHelp:t.accountHelp)}</p>`:`<p class="muted">${escape(t.registrationStudents)}</p>`}
      <section aria-labelledby="title"><div class="row"><h2 id="title">${escape(t.title)}</h2><button type="button" class="info" id="help" title="${escape(t.help)}" aria-label="${escape(t.help)}" aria-expanded="false">i</button></div><p id="help-text" hidden>${escape(t.help)}</p><p class="muted">${escape(t.timezone)}: ${escape(this.payload.timezone)}</p>
      <label for="dataset">${escape(t.data)}</label><select id="dataset"><option value="general" ${this.key==='general'?'selected':''}>${escape(t.general)}</option>${this.datasets.map(d=>`<option value="${escape(d.key)}" ${this.key===d.key?'selected':''}>${escape(d.label)}${this.embedded||this.entry.enabled.includes(d.key)?'':' — '+escape(t.disabled)}</option>`).join('')}</select>
      <div id="controls"></div>${Object.keys(this.payload.yaml_schedule).length?`<p class="muted">${escape(t.yaml)}</p>`:''}</section>
      <details><summary>${escape(t.summary)}</summary><div class="scroll"><table><thead><tr><th>${escape(t.data)}</th><th>${escape(t.title)}</th></tr></thead><tbody id="summary"></tbody></table></div></details>
      <div class="status" id="message" role="status"></div><footer><button class="primary" id="submit" ${this.busy?'disabled':''}>${escape(t.submit)}</button><button id="reset" ${this.busy?'disabled':''}>${escape(t.reset)}</button><span class="muted" id="dirty"></span></footer></main>`;
    if(this.$('hub')) this.$('hub').onchange=e=>{this.entryId=e.target.value;this.studentId=this.entry.students?.[0]?.id||'';this.key='general';this.message='';this.render();};
    if(this.newHub) {
      const warning=document.createElement('p');warning.id='empty-warning';warning.className='muted';warning.textContent=t.emptyWarning;
      this.$('school_name').closest('section').after(warning);
      for(const field of ['username','password','school_name']) this.$(field).oninput=e=>{this.accountDraft[field]=e.target.value;this.status();};
      for(const input of this.shadowRoot.querySelectorAll('[data-source]')) input.onchange=()=>{this.entry.enabled=[...this.shadowRoot.querySelectorAll('[data-source]:checked')].map(el=>el.dataset.source);this.refreshChoices();this.status();};
    }
    if(this.$('student')) this.$('student').onchange=e=>{this.studentId=e.target.value;this.key='general';this.message='';this.render();};
    this.$('dataset').onchange=e=>{this.key=e.target.value;this.message='';this.controls();this.status();};
    this.$('help').onclick=()=>{const p=this.$('help-text');p.hidden=!p.hidden;this.$('help').setAttribute('aria-expanded',String(!p.hidden));};
    this.$('submit').onclick=()=>this.save();
    this.$('reset').onclick=()=>this.discardDraft();
    this.controls(); this.status();
    if(this.busy) for(const control of this.shadowRoot.querySelectorAll('input,select,button')) control.disabled=true;
  }
  $(id) { return this.shadowRoot.getElementById(id); }
  async discardDraft() {
    if(this.busy) return;
    if(this.newHub){this.drafts[this.entryId]=clone(this.baseline());this.accountDraft={username:'',password:'',school_name:''};this.entry.enabled=[];this.message='';this.render();return;}
    this.busy=true;this.render();
    try {
      const latest=await this.hass.callWS({type:'mashov/schedules/get',language:this.language.split('-')[0]});
      const entry=latest.entries.find(e=>e.entry_id===this.entryId);
      if(!entry) throw new Error('unknown_entry');
      this.payload.entries=this.payload.entries.map(e=>e.entry_id===this.entryId?entry:e);
      this.drafts[this.entryId]=clone(this.baseline(entry));
      SCHEDULE_DRAFTS.delete(this.cacheKey(this.entryId));
      if(this.studentId&&!entry.students?.some(s=>s.id===this.studentId))this.studentId=entry.students?.[0]?.id||'';
      this.message='';
    } catch {this.message='error';}
    finally {this.busy=false;this.render();}
  }
  refreshChoices() { for(const option of this.$('dataset').options) {if(option.value==='general') continue;const dataset=this.payload.datasets.find(d=>d.key===option.value);option.textContent=dataset.label+(this.embedded||this.entry.enabled.includes(dataset.key)?'':' — '+this.t.disabled);} }
  controls() {
    const t=this.t, shared=(this.key!=='general'||!!this.studentId)&&!this.current(), s=this.current()||this.effective(this.key), kind=s.schedule_type;
    this.$('controls').innerHTML=`${this.key==='general'&&!this.studentId?'':`<div class="row"><input id="inherit" type="checkbox" ${shared?'checked':''}><label for="inherit">${escape(this.key==='general'?t.inheritDefaults:t.inherit)}</label></div>`}
      <div class="grid"><div><label for="mode">${escape(t.mode)}</label><select id="mode" ${shared?'disabled':''}>${['daily','weekly','interval'].map(k=>`<option value="${k}" ${kind===k?'selected':''}>${escape(t[k])}</option>`).join('')}</select></div>
      ${kind==='interval'?`<div><label for="minutes">${escape(t.minutes)}</label><input id="minutes" type="number" min="5" max="1440" step="1" value="${Number(s.schedule_interval)}" ${shared?'disabled':''}></div>`:`<div><label for="clock">${escape(t.clock)}</label><input id="clock" type="time" step="1" value="${escape(s.schedule_time)}" ${shared?'disabled':''}></div>`}</div>
      ${kind==='weekly'?`<p>${escape(t.days)}</p><div class="days">${[0,1,2,3,4,5,6].map(d=>`<label><input type="checkbox" data-day="${d}" ${s.schedule_days.map(Number).includes(d)?'checked':''} ${shared?'disabled':''}>${escape(this.day(d))}</label>`).join('')}</div>`:''}
      <p class="muted" id="effective-description">${escape(this.describe(this.key))}</p>`;
    if(this.$('inherit')) this.$('inherit').onchange=e=>{const value=clone(this.effective(this.key)),target=this.target(true);if(this.key==='general'){if(e.target.checked)delete target.general;else target.general=value;}else{if(e.target.checked)delete target.overrides[this.key];else target.overrides[this.key]=value;}this.controls();this.status();};
    this.$('mode').onchange=e=>{this.current().schedule_type=e.target.value;this.controls();this.status();};
    if(this.$('clock')) this.$('clock').oninput=e=>{this.current().schedule_time=e.target.value;this.status();};
    if(this.$('minutes')) this.$('minutes').oninput=e=>{this.current().schedule_interval=Number(e.target.value);this.status();};
    for(const input of this.shadowRoot.querySelectorAll('[data-day]')) input.onchange=()=>{this.current().schedule_days=[...this.shadowRoot.querySelectorAll('[data-day]:checked')].map(el=>Number(el.dataset.day));this.status();};
  }
  status() {
    if(this.embedded && this.draft && JSON.stringify(this._value)!==JSON.stringify(this.draft)){this._value=clone(this.draft);this.dispatchEvent(new CustomEvent('value-changed',{detail:{value:clone(this._value)},bubbles:true,composed:true}));}
    if(this.$('empty-warning')) this.$('empty-warning').hidden=this.entry.enabled.length>0;
    this.$('effective-description').textContent=this.describe(this.key);
    this.$('dirty').textContent=this.dirty?this.t.draft:this.t.clean;
    this.$('message').textContent=this.errorCodes?.length?this.errorCodes.map(code=>this.payload.errors?.[code]||this.t[code]||this.t.error).join(' '):(this.t[this.message]||'');
    this.$('summary').innerHTML=[{key:'general',label:this.t.general},...this.datasets].map(d=>`<tr><td>${escape(d.label)}</td><td>${escape(this.describe(d.key))}</td></tr>`).join('');
  }
  async save() {
    if(this.busy) return;
    if(this.newHub && ['username','password','school_name'].some(field=>!this.$(field).reportValidity())) return;
    this.errorCodes=[];
    this.busy=true; for(const control of this.shadowRoot.querySelectorAll('input,select,button')) control.disabled=true;
    try {
      if(this.newHub) {
        const result=await this.hass.callApi('POST','mashov/hub/register',{...this.accountDraft,enabled_data:[...this.entry.enabled],general:clone(this.draft.general),overrides:clone(this.draft.overrides)});
        this.accountDraft.password='';
        if(!result.created){this.errorCodes=result.errors;return;}
        const created=this.entry;this.newHub=false;created.entry_id=result.entry_id;created.revision=result.revision;created.title=this.accountDraft.school_name;this.entryId=result.entry_id;
        this.drafts[this.entryId]=this.drafts.new;delete this.drafts.new;
        this.entry.general=clone(this.draft.general);this.entry.overrides=clone(this.draft.overrides);
        this.message='created';
        try {
          const metadata=await this.hass.callWS({type:'mashov/schedules/get',language:this.language.split('-')[0]});
          this.payload.entries=metadata.entries;this.studentId=this.entry?.students?.[0]?.id||'';
          for(const entry of this.payload.entries) if(!this.drafts[entry.entry_id] || entry.entry_id===this.entryId) this.drafts[entry.entry_id]=clone(this.baseline(entry));
        } catch { /* The hub was created; keep its confirmed schedule draft visible. */ }
        this.render();return;
      }
      const result=await this.hass.callWS({type:'mashov/schedules/save',entry_id:this.entryId,revision:this.entry.revision,...clone(this.draft)});
      SCHEDULE_DRAFTS.delete(this.cacheKey(this.entryId));this.entry.revision=result.revision;this.entry.general=clone(this.draft.general);this.entry.overrides=clone(this.draft.overrides);this.entry.student_schedules=clone(this.draft.student_schedules);this.message='saved';
    } catch(error) {this.message=error.code==='settings_changed'?'changed':error.code==='invalid_schedule'?'invalid':'error';}
    finally {this.busy=false;this.render();}
  }
}
if(!customElements.get('mashov-schedule-editor')) customElements.define('mashov-schedule-editor',MashovScheduleEditor);


class MashovInlineScheduleSelector extends MashovScheduleEditor {
  constructor(){super();this.embedded=true;}
  connectedCallback(){this.setAttribute('embedded','');super.connectedCallback();}
  set selector(value){this.inlineConfig=value?.mashov_schedule;}
  set value(value){this._value=clone(value||{});}
  get value(){return this._value;}
  reportValidity(){
    const value=this.draft||this._value;
    if(!value?.general) return false;
    const schedules=[value.general,...Object.values(value.overrides||{}),...Object.values(value.student_schedules||{}).flatMap(s=>[...(s.general?[s.general]:[]),...Object.values(s.overrides||{})])];
    return schedules.every(s=>s.schedule_type==='interval'?Number.isInteger(Number(s.schedule_interval))&&Number(s.schedule_interval)>=5&&Number(s.schedule_interval)<=1440:/^([01]?[0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?$/.test(s.schedule_time)&&(s.schedule_type!=='weekly'||s.schedule_days?.length>0));
  }
}
if(!customElements.get('ha-selector-mashov_schedule'))customElements.define('ha-selector-mashov_schedule',MashovInlineScheduleSelector);
