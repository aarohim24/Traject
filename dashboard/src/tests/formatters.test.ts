/**
 * formatters.test.ts — unit tests for display formatting utilities.
 *
 * Tests formatTokens, formatCost, and formatPct pure functions
 * with specific values and edge cases.
 */

import { describe, expect, it } from "vitest";
import {
  formatCost,
  formatPct,
  formatTokens,
} from "../lib/formatters";

// ---------------------------------------------------------------------------
// formatTokens
// ---------------------------------------------------------------------------

describe("formatTokens", () => {
  it("formats values below 1000 with no separator", () => {
    expect(formatTokens(0)).toBe("0");
    expect(formatTokens(999)).toBe("999");
  });

  it("formats 1000 with a comma separator", () => {
    expect(formatTokens(1000)).toBe("1,000");
  });

  it("formats 1234567 with comma separators", () => {
    expect(formatTokens(1234567)).toBe("1,234,567");
  });

  it("formats 10000 correctly", () => {
    expect(formatTokens(10000)).toBe("10,000");
  });

  it("formats 1000000 correctly", () => {
    expect(formatTokens(1000000)).toBe("1,000,000");
  });
});

// ---------------------------------------------------------------------------
// formatCost
// ---------------------------------------------------------------------------

describe("formatCost", () => {
  it("returns $0.00 for NaN input", () => {
    expect(formatCost("not-a-number")).toBe("$0.00");
  });

  it("uses 6 decimal places for values < 0.01", () => {
    const result = formatCost(0.000123);
    expect(result).toBe("$0.000123");
    // Verify exactly 6 decimal places
    const decimals = result.split(".")[1];
    expect(decimals).toHaveLength(6);
  });

  it("uses 6 decimal places for 0.000001", () => {
    const result = formatCost(0.000001);
    expect(result).toBe("$0.000001");
  });

  it("uses 4 decimal places for values between 0.01 and 1.0", () => {
    const result = formatCost(0.0123);
    expect(result).toBe("$0.0123");
    const decimals = result.split(".")[1];
    expect(decimals).toHaveLength(4);
  });

  it("uses 2 decimal places for values >= 1.0", () => {
    const result = formatCost(5.5);
    expect(result).toBe("$5.50");
    const decimals = result.split(".")[1];
    expect(decimals).toHaveLength(2);
  });

  it("uses 2 decimal places for exactly 1.0", () => {
    expect(formatCost(1.0)).toBe("$1.00");
  });

  it("uses 2 decimal places for large values", () => {
    expect(formatCost(100.99)).toBe("$100.99");
  });

  it("accepts cost as a numeric string", () => {
    expect(formatCost("0.000123")).toBe("$0.000123");
  });

  it("accepts cost as a string >= 1.0", () => {
    expect(formatCost("5.50")).toBe("$5.50");
  });

  it("uses 6 decimal places for 0.009999 (just below 0.01)", () => {
    const result = formatCost(0.009999);
    expect(result).toMatch(/^\$0\.\d{6}$/);
  });

  it("uses 2 decimal places for 0 (falls into < 0.01 → 6 decimals)", () => {
    // 0 < 0.01, so 6 decimal places
    expect(formatCost(0)).toBe("$0.000000");
  });
});

// ---------------------------------------------------------------------------
// formatPct
// ---------------------------------------------------------------------------

describe("formatPct", () => {
  it("formats 0.8234 as 82.3%", () => {
    expect(formatPct(0.8234)).toBe("82.3%");
  });

  it("formats 0 as 0.0%", () => {
    expect(formatPct(0)).toBe("0.0%");
  });

  it("formats 1 as 100.0%", () => {
    expect(formatPct(1)).toBe("100.0%");
  });

  it("clamps negative values to 0.0%", () => {
    expect(formatPct(-0.5)).toBe("0.0%");
  });

  it("clamps values above 1 to 100.0%", () => {
    expect(formatPct(1.5)).toBe("100.0%");
  });

  it("rounds to 1 decimal place", () => {
    // 0.756 * 100 = 75.6 → rounds to 75.6%
    expect(formatPct(0.756)).toBe("75.6%");
  });

  it("formats 0.5 as 50.0%", () => {
    expect(formatPct(0.5)).toBe("50.0%");
  });
});
