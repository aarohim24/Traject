/**
 * Cost calculator for the Axon TypeScript SDK.
 *
 * Uses BigInt arithmetic scaled to 8 decimal places for all monetary
 * calculations. No floating-point arithmetic is used for currency values
 * (ADR-006 equivalent for TypeScript).
 */

import { PRICING } from "./pricing";

/**
 * Convert a price-per-1M-tokens string to a BigInt in units of 1e-8 USD.
 *
 * Internally the result represents (price_usd_per_1M * 1e8) as a BigInt,
 * so that multiplying by a token count and dividing by 1_000_000 yields
 * total cost in units of 1e-8 USD without any floating-point operations.
 */
function priceStringToUnits(priceStr: string): bigint {
  // We allow at most 8 decimal places in the price string.
  const parts = priceStr.split(".");
  const intPart = parts[0] ?? "0";
  const fracPart = (parts[1] ?? "").padEnd(8, "0").slice(0, 8);
  return BigInt(intPart) * BigInt("100000000") + BigInt(fracPart);
}

/**
 * Calculate the USD cost of an LLM inference call using string-based
 * fixed-point arithmetic.
 *
 * No floating-point arithmetic is used for monetary values. The result is
 * a string with exactly 8 decimal places (e.g. `"0.00250000"`).
 *
 * @param model - The model identifier (e.g. `"gpt-4o"`).
 * @param inputTokens - Number of input/prompt tokens.
 * @param outputTokens - Number of output/completion tokens.
 * @param cachedTokens - Tokens served from provider cache; billed at the
 *   `cacheReadCostPer1MTokens` rate. Defaults to `0`.
 * @returns Cost string with 8 decimal places, or `null` for unknown models.
 */
export function calculateCost(
  model: string,
  inputTokens: number,
  outputTokens: number,
  cachedTokens = 0,
): string | null {
  const pricing = PRICING[model];
  if (pricing === undefined) {
    return null;
  }

  if (inputTokens === 0 && outputTokens === 0 && cachedTokens === 0) {
    return "0.00000000";
  }

  // Scale factor: 1 USD = 100_000_000 units (1e8)
  const ONE_MILLION = BigInt("1000000");
  const SCALE = BigInt("100000000"); // 1e8

  const inputRate = priceStringToUnits(pricing.inputCostPer1MTokens);
  const outputRate = priceStringToUnits(pricing.outputCostPer1MTokens);

  // Regular (non-cached) input tokens
  const regularInput = BigInt(Math.max(0, inputTokens - cachedTokens));
  let total = (regularInput * inputRate) / ONE_MILLION;
  total += (BigInt(outputTokens) * outputRate) / ONE_MILLION;

  // Cached tokens billed at cache-read rate (falls back to input rate)
  if (cachedTokens > 0) {
    const cacheRate =
      pricing.cacheReadCostPer1MTokens !== undefined
        ? priceStringToUnits(pricing.cacheReadCostPer1MTokens)
        : inputRate;
    total += (BigInt(cachedTokens) * cacheRate) / ONE_MILLION;
  }

  // Format: total is in units of 1e-8 USD
  const whole = total / SCALE;
  const frac = total % SCALE;
  return `${whole.toString()}.${frac.toString().padStart(8, "0")}`;
}
