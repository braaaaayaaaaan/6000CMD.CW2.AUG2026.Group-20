export const ACTIVITY_SERIES = [
  { key: "login_failed", label: "Failed Sign-ins", color: "#2563eb", palette: "red" },
  { key: "access_denied", label: "Blocked Access", color: "#19a99a", palette: "orange", dash: "6 4" },
  { key: "asset_downloaded", label: "Asset Downloads", color: "#d59328", palette: "blue" },
];

export function buildActivityTimeline(overview) {
  const start = Date.parse(overview.start);
  const end = Date.parse(overview.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return [];
  const step = Number(overview.hours) === 24 ? 3600000 : 86400000;
  const first = Math.floor(start / step) * step;
  const last = Math.floor(end / step) * step;
  const rows = new Map();
  // The API supports at most 30 days. Bound malformed responses as well.
  if ((last - first) / step > 744) return [];
  for (let time = first; time <= last; time += step) {
    rows.set(time, { time, login_failed: 0, access_denied: 0, asset_downloaded: 0 });
  }
  for (const event of overview.activity || []) {
    const row = rows.get(Date.parse(event.period));
    if (row && ACTIVITY_SERIES.some((series) => series.key === event.event_type) && Number.isSafeInteger(event.count) && event.count >= 0) {
      row[event.event_type] += event.count;
    }
  }
  return [...rows.values()];
}

export function activityScale(maximum) {
  const rawStep = Math.max(1, maximum / 4);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const step = Math.max(1, Math.ceil([1, 2, 2.5, 5, 10].find((value) => value * magnitude >= rawStep) * magnitude));
  const top = Math.max(4, Math.ceil(maximum / step) * step);
  return { top, ticks: Array.from({ length: Math.round(top / step) + 1 }, (_, index) => index * step) };
}

export function activityTickIndexes(length, width) {
  if (!length) return [];
  const count = Math.min(length, Math.max(2, Math.floor(width / 120)));
  return [...new Set(Array.from({ length: count }, (_, index) => Math.round(index * (length - 1) / Math.max(1, count - 1))))];
}

