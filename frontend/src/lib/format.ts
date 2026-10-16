/* Formatting helpers. Amounts are integer minor units; times are ISO strings in UTC. */

const ZERO_DECIMAL = new Set(["JPY", "KRW", "VND", "CLP", "ISK"]);

export function minorExponent(currency: string): number {
  return ZERO_DECIMAL.has(currency.toUpperCase()) ? 0 : 2;
}

/** Group an integer string the Indian way: 1234567 -> 12,34,567. */
export function groupIndian(intDigits: string): string {
  if (intDigits.length <= 3) return intDigits;
  const last3 = intDigits.slice(-3);
  const rest = intDigits.slice(0, -3);
  return rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last3;
}

function groupWestern(intDigits: string): string {
  return intDigits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

const SYMBOLS: Record<string, string> = { INR: "₹", USD: "$", EUR: "€", GBP: "£" };

/**
 * Format integer minor units. INR uses Indian grouping and drops ".00" when whole:
 * 12345600 -> ₹1,23,456 ; 12345650 -> ₹1,23,456.50
 */
export function formatMoney(minor: number | null | undefined, currency = "INR", opts: { alwaysDecimals?: boolean } = {}): string {
  if (minor === null || minor === undefined || Number.isNaN(minor)) return "—";
  const cur = currency.toUpperCase();
  const exp = minorExponent(cur);
  const neg = minor < 0;
  const abs = Math.abs(Math.round(minor));
  const div = 10 ** exp;
  const whole = Math.floor(abs / div).toString();
  const frac = exp ? (abs % div).toString().padStart(exp, "0") : "";
  const grouped = cur === "INR" ? groupIndian(whole) : groupWestern(whole);
  const showFrac = exp > 0 && (opts.alwaysDecimals || Number(frac) !== 0);
  const sym = SYMBOLS[cur] ?? cur + " ";
  return `${neg ? "−" : ""}${sym}${grouped}${showFrac ? "." + frac : ""}`;
}

export function formatMoneyRange(min: number | null | undefined, max: number | null | undefined, currency = "INR"): string {
  if (min === null || min === undefined) return formatMoney(max, currency);
  if (max === null || max === undefined || min === max) return formatMoney(min, currency);
  return `${formatMoney(min, currency)}–${formatMoney(max, currency)}`;
}

/** Parse backend ISO strings (which may carry microseconds) safely. */
export function parseIso(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  let s = iso.replace(/(\.\d{3})\d+/, "$1");
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) s += "Z";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

const IST_OFFSET_MIN = 330;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (n: number) => n.toString().padStart(2, "0");

function parts(d: Date, offsetMin: number) {
  const t = new Date(d.getTime() + offsetMin * 60_000);
  return { y: t.getUTCFullYear(), mo: t.getUTCMonth(), d: t.getUTCDate(), h: t.getUTCHours(), mi: t.getUTCMinutes(), s: t.getUTCSeconds() };
}

/** "16 Oct 2026, 23:14 IST" (deterministic: fixed +05:30, no DST in India). */
export function formatIST(iso: string | null | undefined, opts: { seconds?: boolean; dateOnly?: boolean; suffix?: boolean } = {}): string {
  const d = parseIso(iso);
  if (!d) return "—";
  const p = parts(d, IST_OFFSET_MIN);
  const date = `${p.d} ${MONTHS[p.mo]} ${p.y}`;
  if (opts.dateOnly) return date;
  const time = `${pad(p.h)}:${pad(p.mi)}${opts.seconds ? ":" + pad(p.s) : ""}`;
  return `${date}, ${time}${opts.suffix === false ? "" : " IST"}`;
}

/** "2026-10-16 17:44:00 UTC" for titles / hovers. */
export function formatUTC(iso: string | null | undefined): string {
  const d = parseIso(iso);
  if (!d) return "—";
  const p = parts(d, 0);
  return `${p.y}-${pad(p.mo + 1)}-${pad(p.d)} ${pad(p.h)}:${pad(p.mi)}:${pad(p.s)} UTC`;
}

/** Short time-of-day in IST, e.g. "23:14". */
export function formatISTTime(iso: string | null | undefined): string {
  const d = parseIso(iso);
  if (!d) return "—";
  const p = parts(d, IST_OFFSET_MIN);
  return `${pad(p.h)}:${pad(p.mi)}`;
}

/** Human duration for remaining hours: 2021 -> "84d 5h"; 5.5 -> "5h 30m"; negative -> "breached 3h ago". */
export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || Number.isNaN(hours)) return "—";
  const neg = hours < 0;
  const h = Math.abs(hours);
  let s: string;
  if (h >= 48) {
    const total = Math.round(h);
    const days = Math.floor(total / 24);
    const rem = total % 24;
    s = rem ? `${days}d ${rem}h` : `${days}d`;
  } else if (h >= 1) {
    const whole = Math.floor(h);
    const m = Math.round((h - whole) * 60);
    s = m ? `${whole}h ${m}m` : `${whole}h`;
  } else {
    s = `${Math.round(h * 60)}m`;
  }
  return neg ? `breached ${s} ago` : s;
}

export type SlaTone = "breached" | "urgent" | "ok" | "none";
export function slaTone(hours: number | null | undefined): SlaTone {
  if (hours === null || hours === undefined) return "none";
  if (hours < 0) return "breached";
  if (hours < 24) return "urgent";
  return "ok";
}

export function formatPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function formatUsd(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v === 0) return "$0.00";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(v < 1 ? 3 : 2)}`;
}

export function formatInt(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("en-IN");
}

export function formatMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v >= 1000) return `${(v / 1000).toFixed(v >= 10_000 ? 0 : 1)} s`;
  return `${Math.round(v)} ms`;
}

export function shortHash(h: string | null | undefined, n = 10): string {
  if (!h) return "—";
  return h.slice(0, n);
}

export function humanize(key: string | null | undefined): string {
  if (!key) return "";
  const s = key.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
