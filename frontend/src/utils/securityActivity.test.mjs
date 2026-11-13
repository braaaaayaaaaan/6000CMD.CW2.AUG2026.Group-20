import assert from "node:assert/strict";
import test from "node:test";
import { activityScale, activityTickIndexes, buildActivityTimeline } from "./securityActivity.mjs";

const overview = { start: "2026-11-12T02:07:00Z", end: "2026-11-13T02:07:00Z", hours: 24, activity: [] };

test("hourly data includes partial boundary hours and fills gaps with zero", () => {
  const rows = buildActivityTimeline({ ...overview, activity: [{ period: "2026-11-12T04:00:00Z", event_type: "login_failed", count: 5 }] });
  assert.equal(rows.length, 25);
  assert.equal(rows[0].time, Date.parse("2026-11-12T02:00:00Z"));
  assert.equal(rows.at(-1).time, Date.parse("2026-11-13T02:00:00Z"));
  assert.equal(rows[1].login_failed, 0);
  assert.equal(rows[2].login_failed, 5);
  assert.equal(rows[2].asset_downloaded, 0);
});

test("daily data uses UTC dates including partial first and last days", () => {
  for (const days of [7, 30]) {
    const end = new Date(Date.parse(overview.start) + days * 86400000).toISOString();
    const rows = buildActivityTimeline({ ...overview, hours: days * 24, end });
    assert.equal(rows.length, days + 1);
    assert.equal(new Date(rows[0].time).getUTCHours(), 0);
    assert.equal(rows[1].time - rows[0].time, 86400000);
  }
});

test("duplicate buckets accumulate and unrelated or invalid records are ignored", () => {
  const event = { period: "2026-11-12T04:00:00Z", event_type: "asset_downloaded", count: 3 };
  const rows = buildActivityTimeline({ ...overview, activity: [event, event,
    { ...event, count: -1 }, { ...event, count: 1.5 }, { ...event, count: "9" },
    { ...event, event_type: "asset_previewed" }, { ...event, period: "invalid" },
    { ...event, period: "2026-11-11T04:00:00Z" },
  ] });
  assert.equal(rows[2].asset_downloaded, 6);
  assert.equal(rows.reduce((sum, row) => sum + row.asset_downloaded, 0), 6);
});

test("an empty response shows a genuine zero baseline rather than invented activity", () => {
  assert.ok(buildActivityTimeline(overview).every((row) => row.login_failed === 0 && row.access_denied === 0 && row.asset_downloaded === 0));
});

test("malformed or unbounded date ranges cannot generate an invalid chart", () => {
  assert.deepEqual(buildActivityTimeline({ ...overview, start: "invalid" }), []);
  assert.deepEqual(buildActivityTimeline({ ...overview, end: "2026-11-10T00:00:00Z" }), []);
  assert.deepEqual(buildActivityTimeline({ ...overview, end: "2030-01-01T00:00:00Z" }), []);
});

test("count axes have integer ticks, a zero origin and room for the highest value", () => {
  for (const maximum of [0, 1, 3, 6, 10, 21, 100, 850, 10000]) {
    const { top, ticks } = activityScale(maximum);
    assert.ok(top >= maximum);
    assert.equal(ticks[0], 0);
    assert.equal(ticks.at(-1), top);
    assert.ok(ticks.every(Number.isInteger));
    assert.ok(ticks.length >= 3 && ticks.length <= 6);
  }
});

test("responsive labels include both ends without duplicate or invalid indexes", () => {
  for (const length of [1, 8, 25, 31]) {
    for (const width of [240, 600, 1000]) {
      const indexes = activityTickIndexes(length, width);
      assert.equal(indexes[0], 0);
      assert.equal(indexes.at(-1), length - 1);
      assert.equal(indexes.length, new Set(indexes).size);
      assert.ok(indexes.every((index) => index >= 0 && index < length));
    }
  }
  assert.deepEqual(activityTickIndexes(0, 600), []);
});
