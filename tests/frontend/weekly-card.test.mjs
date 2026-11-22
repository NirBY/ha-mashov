import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
globalThis.HTMLElement = class {};
globalThis.customElements = {get(){},define(){}};
const source = await readFile(new URL("../../custom_components/mashov/weekly-card.js",import.meta.url),"utf8");
const {schoolWeek,schoolDays,dateInZone} = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
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
