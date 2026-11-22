import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

globalThis.HTMLElement = class {
  attachShadow() { this.shadowRoot = { addEventListener() {} }; }
};
globalThis.customElements = { get() {}, define() {} };
const source = await readFile(new URL("../../custom_components/mashov/homework-card.js", import.meta.url), "utf8");
const { groupHomework, reportedDate, escapeHTML, readHomework, setHomeworkCompleted, MashovHomeworkCard } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const task = (uid, date, status = "needs_action") => ({ uid, summary: `Math ${uid}`, description: `${date} · A lesson`, status });

test("last three homework dates span gaps and keep every task on each date", () => {
  const items = [task("a", "2026-11-18"), task("b", "2026-11-18"), task("c", "2026-11-15"), task("d", "2026-11-03"), task("e", "2026-10-25")];
  const recent = groupHomework(items);
  assert.deepEqual(recent.groups.map(g => g.date), ["2026-11-18", "2026-11-15", "2026-11-03"]);
  assert.equal(recent.groups[0].items.length, 2);
  assert.equal(recent.olderDays, 1);
  assert.equal(groupHomework(items, 3, true).groups.length, 4);
  assert.equal(items.length, 5);
});

test("completed lines stay in the same group and position; equal names keep distinct UIDs", () => {
  const items = [task("b", "2026-11-18"), task("a", "2026-11-18"), task("c", "2026-11-15")];
  const before = groupHomework(items).groups[0].items.map(i => i.uid);
  items[1].status = "completed";
  assert.deepEqual(groupHomework(items).groups[0].items.map(i => i.uid), before);
  assert.equal(groupHomework(items).groups[0].items[0].status, "completed");
  assert.equal(groupHomework([{ ...items[0], summary: "same" }, { ...items[1], summary: "same" }]).groups[0].items.length, 2);
});

test("dates are assignment dates, with undated tasks retained and invalid dates rejected", () => {
  assert.equal(reportedDate({ description: "2026-02-30 · invalid", due: "2026-11-22" }), "");
  assert.equal(reportedDate({ due: "2026-11-22" }), "");
  const result = groupHomework([task("a", "2026-11-18"), { uid: "undated", summary: "Read" }]);
  assert.equal(result.groups.at(-1).date, "");
  assert.equal(result.groups.at(-1).items[0].uid, "undated");
});

test("school text is escaped, never interpreted as markup or checkbox attributes", () => {
  assert.equal(escapeHTML('<img src=x onerror="run()"> & \'x\''), "&lt;img src=x onerror=&quot;run()&quot;&gt; &amp; &#39;x&#39;");
});

test("reads include completed items and validate the selected child response", async () => {
  let request;
  const items = [task("a", "2026-11-18", "completed")];
  assert.deepEqual(await readHomework({ callWS: async value => { request = value; return { response: { "todo.child": { items } } }; } }, "todo.child"), items);
  assert.equal(request.service, "get_items");
  assert.equal(request.service_data.entity_id, "todo.child");
  assert.equal(request.service_data.status, undefined);
  await assert.rejects(readHomework({ callWS: async () => ({ response: { "todo.other": { items } } }) }, "todo.child"));
});

test("checking and unchecking only update status by UID, never remove or rename", async () => {
  const calls = [];
  const hass = { callService: async (...args) => calls.push(args) };
  await setHomeworkCompleted(hass, "todo.child", "specific-uid", true);
  await setHomeworkCompleted(hass, "todo.child", "specific-uid", false);
  assert.deepEqual(calls.map(c => c.slice(0, 4)), [
    ["todo", "update_item", { item: "specific-uid", status: "completed" }, { entity_id: "todo.child" }],
    ["todo", "update_item", { item: "specific-uid", status: "needs_action" }, { entity_id: "todo.child" }],
  ]);
});

function cardFor(hass) {
  const card = new MashovHomeworkCard();
  card._render = () => {};
  card.setConfig({ entity: "todo.child" });
  card._hass = hass;
  card._available = true;
  card._items = [task("a", "2026-11-18")];
  return card;
}

test("a failed save leaves the row present and unchecked, with a retry message", async () => {
  const card = cardFor({ callService: async () => { throw new Error("disk unavailable"); } });
  await card._toggle("a", true);
  assert.equal(card._items.length, 1);
  assert.equal(card._items[0].status, "needs_action");
  assert.equal(card._error, "failed");
  assert.equal(card._busy.size, 0);
});

test("a read for a previous child cannot populate a newly selected child card", async () => {
  let finish;
  const card = cardFor({ callWS: () => new Promise(resolve => { finish = resolve; }) });
  const read = card._load();
  card._hass = null;
  card.setConfig({ entity: "todo.other" });
  finish({ response: { "todo.child": { items: [task("private", "2026-11-18")] } } });
  await read;
  assert.deepEqual(card._items, []);
});

test("a stale read cannot undo a saved checkmark", async () => {
  let finishOld;
  let reads = 0;
  const card = cardFor({
    callService: async () => {},
    callWS: async () => ++reads === 1 ? new Promise(resolve => { finishOld = resolve; }) : ({ response: { "todo.child": { items: [task("a", "2026-11-18", "completed")] } } }),
  });
  const read = card._load();
  await card._toggle("a", true);
  finishOld({ response: { "todo.child": { items: [task("a", "2026-11-18")] } } });
  await read;
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(card._items[0].status, "completed");
});
