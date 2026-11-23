/** Date/time helpers: UTC over the wire, user-readable local time in the UI. */

export function parseUtc(value: string): Date {
  // API timestamps are RFC3339 UTC ('Z' suffix); normalize '+00:00' forms.
  const normalized = value.replace(/\+00:00$/, "Z");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    throw new Error(`invalid timestamp: ${value}`);
  }
  return date;
}

const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
});

export function formatDateTime(value: string): string {
  return dateTimeFormatter.format(parseUtc(value));
}

export function formatDate(value: string): string {
  return dateFormatter.format(parseUtc(value));
}

export function formatUtcExact(value: string): string {
  return parseUtc(value).toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

export function relativeTime(value: string, now: Date = new Date()): string {
  const then = parseUtc(value).getTime();
  const diffMs = then - now.getTime();
  const absMinutes = Math.abs(Math.round(diffMs / 60_000));
  const future = diffMs > 0;
  if (absMinutes < 1) return "now";
  if (absMinutes < 60) return future ? `in ${absMinutes} min` : `${absMinutes} min ago`;
  const hours = Math.round(absMinutes / 60);
  if (hours < 24) return future ? `in ${hours} h` : `${hours} h ago`;
  const days = Math.round(hours / 24);
  return future ? `in ${days} d` : `${days} d ago`;
}

/** Convert a local datetime-input value to a UTC RFC3339 string. */
export function localInputToUtc(local: string): string {
  const date = new Date(local);
  if (Number.isNaN(date.getTime())) {
    throw new Error(`invalid datetime input: ${local}`);
  }
  return date.toISOString();
}

/** Default suggestion for a pickup window start (next hour, on the hour). */
export function nextHourLocal(): string {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return toLocalInputValue(d);
}

export function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}
