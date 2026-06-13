/**
 * formatters — display formatting utilities for tokens, costs, and percentages.
 *
 * All monetary values are passed as strings from the backend and formatted here
 * for display only. No arithmetic is performed on cost values.
 */

/**
 * Format a token count with comma separators.
 *
 * @param n - Raw token count (integer).
 * @returns Formatted string, e.g. `1234567` → `"1,234,567"`.
 */
export function formatTokens(n: number): string {
  return n.toLocaleString("en-US");
}

/**
 * Format a USD cost value with variable decimal precision.
 *
 * Rules:
 * - Value < $0.01  → 6 decimal places (e.g. `"$0.000123"`)
 * - Value >= $1.00 → 2 decimal places (e.g. `"$1.23"`)
 * - Otherwise      → 4 decimal places (e.g. `"$0.0123"`)
 *
 * @param usd - Cost as a string or number. Strings are parsed via `parseFloat`.
 * @returns Formatted cost string prefixed with `$`.
 */
export function formatCost(usd: string | number): string {
  const value = typeof usd === "string" ? parseFloat(usd) : usd;

  if (isNaN(value)) {
    return "$0.00";
  }

  let decimals: number;
  if (value < 0.01) {
    decimals = 6;
  } else if (value >= 1.0) {
    decimals = 2;
  } else {
    decimals = 4;
  }

  return `$${value.toFixed(decimals)}`;
}

/**
 * Format a ratio as a percentage string, clamped to [0, 1] and rounded to 1 decimal place.
 *
 * @param ratio - A value between 0 and 1 (e.g. `0.8234`).
 * @returns Formatted percentage string, e.g. `"82.3%"`.
 */
export function formatPct(ratio: number): string {
  const clamped = Math.min(1, Math.max(0, ratio));
  return `${(clamped * 100).toFixed(1)}%`;
}
