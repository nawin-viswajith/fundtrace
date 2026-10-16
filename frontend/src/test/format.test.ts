import { describe, expect, it } from "vitest";
import { formatHours, formatIST, formatMoney, formatMoneyRange, formatUTC, groupIndian, parseIso, slaTone } from "../lib/format";

describe("money formatting", () => {
  it("groups INR the Indian way and drops .00 when whole", () => {
    expect(formatMoney(12345600, "INR")).toBe("₹1,23,456");
    expect(formatMoney(5000000, "INR")).toBe("₹50,000");
    expect(formatMoney(1234567890, "INR")).toBe("₹1,23,45,678.90");
    expect(formatMoney(64900, "INR")).toBe("₹649");
  });
  it("keeps paise when not whole", () => {
    expect(formatMoney(1795615, "INR")).toBe("₹17,956.15");
    expect(formatMoney(12345650, "INR")).toBe("₹1,23,456.50");
  });
  it("can force decimals", () => {
    expect(formatMoney(12345600, "INR", { alwaysDecimals: true })).toBe("₹1,23,456.00");
  });
  it("handles zero, negatives and missing values", () => {
    expect(formatMoney(0, "INR")).toBe("₹0");
    expect(formatMoney(-150000, "INR")).toBe("−₹1,500");
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
  });
  it("uses western grouping for other currencies", () => {
    expect(formatMoney(123456700, "USD")).toBe("$1,234,567");
  });
  it("groups digits", () => {
    expect(groupIndian("999")).toBe("999");
    expect(groupIndian("1000")).toBe("1,000");
    expect(groupIndian("100000")).toBe("1,00,000");
    expect(groupIndian("10000000")).toBe("1,00,00,000");
  });
  it("formats ranges", () => {
    expect(formatMoneyRange(2880000, 3000000)).toBe("₹28,800–₹30,000");
    expect(formatMoneyRange(2000000, 2000000)).toBe("₹20,000");
  });
});

describe("time formatting", () => {
  it("shows IST (UTC+5:30) on screen", () => {
    expect(formatIST("2026-10-16T17:44:00Z")).toBe("16 Oct 2026, 23:14 IST");
    expect(formatIST("2026-10-16T19:00:00Z")).toBe("17 Oct 2026, 00:30 IST");
    expect(formatIST("2026-10-16T17:44:05Z", { seconds: true })).toBe("16 Oct 2026, 23:14:05 IST");
    expect(formatIST("2026-10-16T17:44:00Z", { dateOnly: true })).toBe("16 Oct 2026");
  });
  it("gives UTC for hover titles", () => {
    expect(formatUTC("2026-10-16T17:44:00Z")).toBe("2026-10-16 17:44:00 UTC");
  });
  it("parses microsecond timestamps from the backend", () => {
    expect(parseIso("2026-10-16T19:19:09.613864Z")?.toISOString()).toBe("2026-10-16T19:19:09.613Z");
    expect(parseIso(null)).toBeNull();
    expect(formatIST("not a date")).toBe("—");
  });
  it("formats SLA remaining time and tone", () => {
    expect(formatHours(2021)).toBe("84d 5h");
    expect(formatHours(2087.9)).toBe("87d");
    expect(formatHours(5.5)).toBe("5h 30m");
    expect(formatHours(-46)).toBe("breached 46h ago");
    expect(slaTone(-1)).toBe("breached");
    expect(slaTone(12)).toBe("urgent");
    expect(slaTone(48)).toBe("ok");
    expect(slaTone(null)).toBe("none");
  });
});
