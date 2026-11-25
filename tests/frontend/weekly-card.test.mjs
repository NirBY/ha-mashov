import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
globalThis.HTMLElement = class {attachShadow(){this.shadowRoot={innerHTML:"",addEventListener(){}};return this.shadowRoot;}};
globalThis.customElements = {get(){},define(){}};
const source = await readFile(new URL("../../custom_components/mashov/weekly-card.js",import.meta.url),"utf8");
const {schoolWeek,schoolDays,dateInZone,MashovWeeklyCard} = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const bells = [0,1,2,3].map(n=>({lessonNumber:n,startTime:`0${n+7}:30:00`,endTime:`${String(n+8).padStart(2,"0")}:15:00`}));
const schedule = [{day:1,lessons:[{lesson:3,subject:"Art"},{lesson:1,subject:"Math"},{lesson:2,subject:"Science"}]}];
test("uses each child's first/last lesson, not first/last school bell",()=>{
  const week = schoolWeek(schedule,bells,[],"2026-11-22");
  assert.equal(week[0].start,"08:30"); assert.equal(week[0].end,"11:15");
  assert.deepEqual(week[0].lessons.map(x=>x.subject),["Math","Science","Art"]);
  assert.equal(week[1].start,""); assert.equal(week[6].date,"2026-11-28");
});
test("published timetable removal recalculates start/end on the next update",()=>{
  const updated = [{day:1,lessons:schedule[0].lessons.filter(x=>x.lesson===2)}];
  assert.equal(schoolWeek(updated,bells,[],"2026-11-22")[0].start,"09:30");
  assert.equal(schoolWeek(updated,bells,[],"2026-11-22")[0].end,"10:15");
  assert.equal(schoolWeek([{day:1,lessons:[]}],bells,[],"2026-11-22")[0].start,"");
});
test("holidays match actual date range; next week uses its own dates",()=>{
  const holidays=[{name:"Holiday",start:"2026-11-22T00:00:00",end:"2026-11-23T00:00:00"}];
  assert.equal(schoolWeek(schedule,bells,holidays,"2026-11-22")[0].start,"");
  assert.equal(schoolWeek(schedule,bells,holidays,"2026-11-22",1)[0].start,"08:30");
});
test("missing times, partial data and alternating weeks never invent hours",()=>{
  assert.equal(schoolWeek(schedule,[],[],"2026-11-22")[0].start,"");
  assert.equal(schoolWeek(schedule,bells,[],"2026-11-22",0,false)[0].end,"");
  const variable=[{day:1,lessons:[{lesson:1,weeks:"2"}]}];
  assert.equal(schoolWeek(variable,bells,[],"2026-11-22")[0].start,"");
});
test("HA timezone controls the school date across UTC midnight",()=>{
  assert.equal(dateInZone(new Date("2026-11-21T23:30:00Z"),"Asia/Jerusalem"),"2026-11-22");
});
test("an interior week-specific lesson does not hide definite boundary times",()=>{
  const variable=[{day:1,lessons:[{lesson:1},{lesson:2,weeks:"0"},{lesson:3}]}];
  const day=schoolWeek(variable,bells,[],"2026-11-22")[0];
  assert.equal(day.start,"08:30");assert.equal(day.end,"11:15");assert.equal(day.variable,true);
});
test("only days with lessons are displayed, including Friday when scheduled",()=>{
  const schedule=[{day:1,lessons:[{lesson:1}]},{day:6,lessons:[{lesson:2}]}];
  assert.deepEqual(schoolDays(schoolWeek(schedule,bells,[],"2026-11-22")).map(x=>x.day),[1,6]);
  const holiday=[{name:"Holiday",start:"2026-11-22",end:"2026-11-28"}];
  assert.deepEqual(schoolDays(schoolWeek(schedule,bells,holiday,"2026-11-22")),[]);
  assert.deepEqual(schoolDays(schoolWeek([],bells,[],"2026-11-22")),[]);
});
test("an upcoming cancelled first lesson starts the day at the next lesson",()=>{
  const week=schoolWeek([{day:1,lessons:[{lesson:1,subject:"Math",cancelled:["2026-11-22"]},{lesson:2,subject:"Science"},{lesson:3,subject:"Art"}]}],bells,[],"2026-11-22");
  assert.equal(week[0].start,"09:30");assert.equal(week[0].end,"11:15");
  assert.equal(week[0].laterStart,true);assert.equal(week[0].earlierEnd,false);
  assert.deepEqual(week[0].lessons.map(x=>x.cancelled),[true,false,false]);
});
test("a cancelled last lesson ends earlier; an interior one moves nothing",()=>{
  const last=schoolWeek([{day:2,lessons:[{lesson:1},{lesson:2},{lesson:3,cancelled:["2026-11-23"]}]}],bells,[],"2026-11-22")[1];
  assert.equal(last.start,"08:30");assert.equal(last.end,"10:15");assert.equal(last.earlierEnd,true);
  const middle=schoolWeek([{day:2,lessons:[{lesson:1},{lesson:2,cancelled:["2026-11-23"]},{lesson:3}]}],bells,[],"2026-11-22")[1];
  assert.equal(middle.start,"08:30");assert.equal(middle.end,"11:15");
  assert.equal(middle.laterStart||middle.earlierEnd,false);assert.equal(middle.lessons[1].cancelled,true);
});
test("past cancellations are marked but keep the published hours",()=>{
  const day=schoolWeek([{day:1,lessons:[{lesson:1,cancelled:["2026-11-22"]},{lesson:2}]}],bells,[],"2026-11-23")[0];
  assert.equal(day.lessons[0].cancelled,true);assert.equal(day.start,"08:30");assert.equal(day.laterStart,false);
  const nextWeek=schoolWeek([{day:1,lessons:[{lesson:1,cancelled:["2026-11-22"]},{lesson:2}]}],bells,[],"2026-11-22",1)[0];
  assert.equal(nextWeek.lessons[0].cancelled,false);assert.equal(nextWeek.start,"08:30");
});
test("a slot moves only when every simultaneous group is cancelled",()=>{
  const partly=[{day:1,lessons:[{lesson:1,subject:"English A",cancelled:["2026-11-22"]},{lesson:1,subject:"English B"},{lesson:2}]}];
  assert.equal(schoolWeek(partly,bells,[],"2026-11-22")[0].start,"08:30");
  const fully=[{day:1,lessons:[{lesson:1,cancelled:["2026-11-22"]},{lesson:1,cancelled:["2026-11-22"]},{lesson:2}]}];
  assert.equal(schoolWeek(fully,bells,[],"2026-11-22")[0].start,"09:30");
});
test("a fully cancelled day has no hours, and a week-specific new first lesson is not guessed",()=>{
  const all=schoolWeek([{day:1,lessons:[{lesson:1,cancelled:["2026-11-22"]},{lesson:2,cancelled:["2026-11-22"]}]}],bells,[],"2026-11-22")[0];
  assert.equal(all.allCancelled,true);assert.equal(all.start,"");assert.equal(all.end,"");assert.equal(all.laterStart,false);
  const weekly=schoolWeek([{day:1,lessons:[{lesson:1,cancelled:["2026-11-22"]},{lesson:2,weeks:"2"},{lesson:3}]}],bells,[],"2026-11-22")[0];
  assert.equal(weekly.start,"");assert.equal(weekly.laterStart,true);assert.equal(weekly.end,"11:15");
});
test("the input schedule is not modified",()=>{
  const input=[{day:1,lessons:[{lesson:1,cancelled:["2026-11-22"]}]}];
  schoolWeek(input,bells,[],"2026-11-22");
  assert.deepEqual(input[0].lessons[0].cancelled,["2026-11-22"]);
});
test("the card shows cancelled lessons, moved hours and the source note",()=>{
  const today=dateInZone(new Date(),"Asia/Jerusalem");
  const day=new Date(today+"T12:00:00Z").getUTCDay()+1;
  const card=new MashovWeeklyCard();
  card.setConfig({entity:"sensor.child_timetable",bells_entity:"sensor.bells",language:"en"});
  const timetable=status=>({state:"3",attributes:{weekly_schedule_complete:true,cancellations_status:status,weekly_schedule:[{day,lessons:[{lesson:1,subject:"Math",cancelled:[today]},{lesson:2,subject:"Science"},{lesson:3,subject:"Art"}]}]}});
  card.hass={config:{time_zone:"Asia/Jerusalem"},states:{"sensor.child_timetable":timetable("ok"),"sensor.bells":{state:"4",attributes:{items:bells}}}};
  const html=card.shadowRoot.innerHTML;
  assert.match(html,/class="lesson cancelled"/);assert.match(html,/<span class="tag">Cancelled<\/span>/);
  assert.match(html,/Later start: cancellation/);assert.match(html,/lesson cancellations published in Mashov/);
  assert.doesNotMatch(html,/could not be loaded/);
  card.hass={config:{time_zone:"Asia/Jerusalem"},states:{"sensor.child_timetable":timetable("not_offered"),"sensor.bells":{state:"4",attributes:{items:bells}}}};
  assert.match(card.shadowRoot.innerHTML,/does not publish lesson cancellations/);
  card.hass={config:{time_zone:"Asia/Jerusalem"},states:{"sensor.child_timetable":timetable("http_503"),"sensor.bells":{state:"4",attributes:{items:bells}}}};
  assert.match(card.shadowRoot.innerHTML,/could not be loaded/);
  card.hass={config:{time_zone:"Asia/Jerusalem"},states:{"sensor.child_timetable":timetable(undefined),"sensor.bells":{state:"4",attributes:{items:bells}}}};
  assert.match(card.shadowRoot.innerHTML,/cancellations published only in messages do not change these times/);
});
