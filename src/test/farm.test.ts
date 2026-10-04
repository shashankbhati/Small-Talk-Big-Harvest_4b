import { describe, it, expect } from "vitest";
import { roundCoord, stepArea, isValidPhone, fullPhone } from "@/lib/farm";

describe("farm rules", () => {
  it("rounds coordinates to 2 decimals", () => {
    expect(roundCoord(12.34567)).toBe(12.35);
    expect(roundCoord(75.8912)).toBe(75.89);
  });
  it("steps field size by 0.5 acre", () => {
    expect(stepArea(1, 1)).toBe(1.5);
    expect(stepArea(1.5, -1)).toBe(1);
    expect(stepArea(0.5, -1)).toBe(0.5);
  });
  it("needs exactly 10 digits", () => {
    expect(isValidPhone("9876543210")).toBe(true);
    expect(isValidPhone("987654321")).toBe(false);
  });
});

describe("country codes", () => {
  it("keeps the 10-digit rule only for +91", () => {
    expect(isValidPhone("9876543210", "+91")).toBe(true);
    expect(isValidPhone("98765432", "+91")).toBe(false);
  });
  it("accepts 7 to 14 digits for +49", () => {
    expect(isValidPhone("1234567", "+49")).toBe(true);
    expect(isValidPhone("12345678901234", "+49")).toBe(true);
    expect(isValidPhone("123456", "+49")).toBe(false);
    expect(isValidPhone("123456789012345", "+49")).toBe(false);
  });
  it("sends the full international number", () => {
    expect(fullPhone("+49", "15112345678")).toBe("+4915112345678");
  });
  it("drops the national leading zero", () => {
    expect(fullPhone("+49", "015112345678")).toBe("+4915112345678");
    expect(fullPhone("+91", "9876543210")).toBe("+919876543210");
  });
});
