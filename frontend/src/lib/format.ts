/** Value-shaping helpers shared by the mappers. Pure, no I/O, no React. */

/** Coerce anything to a finite number, falling back when absent or unparseable. */
export function num(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

/** Clamp into a range, coercing bad input to the fallback first. */
export function clamp(value: unknown, min: number, max: number, fallback = min): number {
  const n = num(value, fallback);
  if (n < min) return min;
  if (n > max) return max;
  return n;
}

/** "flood" -> "Flood", "heavy_rain" -> "Heavy rain". */
export function humanise(value: string | null | undefined, fallback = "Unknown"): string {
  if (!value) return fallback;
  const words = value.replace(/[_-]+/g, " ").trim();
  if (!words) return fallback;
  return words.charAt(0).toUpperCase() + words.slice(1).toLowerCase();
}

/** Parse an ISO timestamp; returns null when absent or unparseable. */
export function parseTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Compact age string in the style the operator console already uses: "8s ago",
 * "12m ago", "3h ago", "2d ago". Returns "" for unknown timestamps.
 */
export function relativeAge(value: string | null | undefined, now = Date.now()): string {
  const date = parseTime(value);
  if (!date) return "";
  const seconds = Math.max(0, Math.round((now - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** Bare age without the "ago" suffix, e.g. "8s" / "12m". */
export function ageShort(value: string | null | undefined, now = Date.now()): string {
  return relativeAge(value, now).replace(" ago", "");
}

/** 12400 -> "12.4K". Keeps small numbers exact. */
export function compactCount(value: unknown): string {
  const n = Math.max(0, Math.round(num(value)));
  if (n < 1000) return String(n);
  if (n < 1_000_000) {
    const thousands = n / 1000;
    return `${thousands >= 100 ? Math.round(thousands) : Number(thousands.toFixed(1))}K`;
  }
  return `${Number((n / 1_000_000).toFixed(1))}M`;
}

/** Percentage from a 0..1 ratio, or from a value already expressed 0..100. */
export function percentFromRatio(value: unknown, fallback = 0): number {
  const n = num(value, NaN);
  if (!Number.isFinite(n)) return fallback;
  return clamp(n <= 1 ? n * 100 : n, 0, 100, fallback);
}

/** Great-circle distance in kilometres. */
export function haversineKm(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number,
): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(a)));
}

/**
 * Drive-time estimate in whole minutes. The backend's flood-aware planner uses
 * 28 km/h and a 3-minute floor; mirror that so team ETAs and route ETAs agree.
 */
export function driveMinutes(km: number): number {
  return Math.max(3, Math.round((km / 28) * 60));
}

/** `true` only for values that are genuinely usable, so callers can fall back. */
export function hasData<T>(value: T | null | undefined): value is T {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}
