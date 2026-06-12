/**
 * Provider pricing table for the Axon TypeScript SDK.
 *
 * Mirrors `sdk/python/axon/core/pricing.py` exactly. All prices are USD per
 * 1 million tokens, stored as string literals to preserve exact decimal
 * representation (ADR-006 equivalent for TypeScript). No floating-point
 * values are used for monetary data.
 */

/**
 * Pricing data for a single LLM model.
 *
 * All cost fields are USD per 1,000,000 tokens represented as decimal strings.
 */
export interface ModelPricing {
  /** Input cost in USD per 1M tokens. */
  inputCostPer1MTokens: string;
  /** Output cost in USD per 1M tokens. */
  outputCostPer1MTokens: string;
  /** Cache read cost in USD per 1M tokens (optional). */
  cacheReadCostPer1MTokens?: string;
  /** Cache write cost in USD per 1M tokens (optional). */
  cacheWriteCostPer1MTokens?: string;
}

/**
 * Pricing table for all supported LLM models.
 *
 * Values are sourced from the canonical Python pricing table and verified
 * against provider pricing pages. Last verified: 2025-01-01.
 */
export const PRICING: Record<string, ModelPricing> = {
  // Source: https://openai.com/api/pricing
  "gpt-4o": {
    inputCostPer1MTokens: "2.50",
    outputCostPer1MTokens: "10.00",
    cacheReadCostPer1MTokens: "1.25",
  },
  "gpt-4o-mini": {
    inputCostPer1MTokens: "0.15",
    outputCostPer1MTokens: "0.60",
    cacheReadCostPer1MTokens: "0.075",
  },
  "gpt-4-turbo": {
    inputCostPer1MTokens: "10.00",
    outputCostPer1MTokens: "30.00",
  },
  "gpt-3.5-turbo": {
    inputCostPer1MTokens: "0.50",
    outputCostPer1MTokens: "1.50",
  },
  // Source: https://www.anthropic.com/pricing
  "claude-3-5-sonnet-20241022": {
    inputCostPer1MTokens: "3.00",
    outputCostPer1MTokens: "15.00",
    cacheReadCostPer1MTokens: "0.30",
    cacheWriteCostPer1MTokens: "3.75",
  },
  "claude-3-5-haiku-20241022": {
    inputCostPer1MTokens: "0.80",
    outputCostPer1MTokens: "4.00",
    cacheReadCostPer1MTokens: "0.08",
    cacheWriteCostPer1MTokens: "1.00",
  },
  "claude-3-opus-20240229": {
    inputCostPer1MTokens: "15.00",
    outputCostPer1MTokens: "75.00",
    cacheReadCostPer1MTokens: "1.50",
    cacheWriteCostPer1MTokens: "18.75",
  },
  "claude-3-haiku-20240307": {
    inputCostPer1MTokens: "0.25",
    outputCostPer1MTokens: "1.25",
  },
};
