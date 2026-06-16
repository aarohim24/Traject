/**
 * Tests for the cost_calculator module.
 *
 * Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5
 */

import { calculateCost } from "../src/cost_calculator";

describe("calculateCost", () => {
  // Validates: Requirements 7.1, 7.5
  it("returns correct cost for gpt-4o with 1M input and 1M output tokens", () => {
    // gpt-4o: $2.50/1M input + $10.00/1M output → $12.50 for 1M+1M
    // (matches sdk/python/traject/core/pricing.py — last verified 2025-01-01)
    const result = calculateCost("gpt-4o", 1_000_000, 1_000_000);
    expect(result).toBe("12.50000000");
  });

  // Validates: Requirements 7.1
  it("returns cost string with exactly 8 decimal places for a fractional cost", () => {
    // gpt-4o-mini: $0.15/1M input + $0.60/1M output
    // 100 input + 100 output = 0.000015 + 0.00006 = 0.000075
    const result = calculateCost("gpt-4o-mini", 100, 100);
    expect(result).not.toBeNull();
    expect(result!.split(".")[1]).toHaveLength(8);
  });

  // Validates: Requirements 7.2
  it("returns null for unknown model", () => {
    expect(calculateCost("unknown-model-xyz", 100, 100)).toBeNull();
  });

  // Validates: Requirements 7.3
  it("returns '0.00000000' for zero tokens on a known model", () => {
    expect(calculateCost("gpt-4o", 0, 0)).toBe("0.00000000");
  });

  // Validates: Requirements 7.3
  it("returns '0.00000000' for zero tokens with cachedTokens=0", () => {
    expect(calculateCost("gpt-4o", 0, 0, 0)).toBe("0.00000000");
  });

  // Validates: Requirements 7.4
  it("bills cached tokens at cache-read rate for claude-3-5-sonnet-20241022", () => {
    // claude-3-5-sonnet: cacheReadCostPer1MTokens = $0.30/1M
    // 0 regular input (all cached), 0 output, 1M cached → 1M * $0.30/1M = $0.30
    const result = calculateCost(
      "claude-3-5-sonnet-20241022",
      1_000_000,
      0,
      1_000_000,
    );
    expect(result).toBe("0.30000000");
  });

  // Validates: Requirements 7.4, 7.5
  it("uses input rate as fallback when model has no cacheReadCost (claude-3-haiku)", () => {
    // claude-3-haiku-20240307: no cacheReadCostPer1MTokens
    // cachedTokens fall back to inputCostPer1MTokens = $0.25/1M
    // 1M cached at $0.25/1M = $0.25
    const result = calculateCost("claude-3-haiku-20240307", 1_000_000, 0, 1_000_000);
    expect(result).toBe("0.25000000");
  });

  // Validates: Requirements 7.5 — no floating-point drift for small values
  it("handles large token counts without floating-point drift", () => {
    // gpt-4-turbo: $10/1M input + $30/1M output
    // 10M input + 10M output = $100 + $300 = $400
    const result = calculateCost("gpt-4-turbo", 10_000_000, 10_000_000);
    expect(result).toBe("400.00000000");
  });
});
