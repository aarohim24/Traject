/**
 * types — all TypeScript interfaces for the Traject backend REST API.
 *
 * Monetary values are represented as strings (decimal notation) to avoid
 * IEEE 754 floating-point rounding errors. Never parse cost strings to
 * `number` — always pass them through `formatCost()` for display.
 */

/** Query parameters for the /v1/attribution endpoint. */
export interface AttributionParams {
  from_ts?: string;
  to_ts?: string;
  feature_tag?: string;
  group_by?: string;
}

/** Per-tag breakdown row returned inside AttributionResponse. */
export interface AttributionByTag {
  feature_tag: string;
  /** Total cost in USD as a decimal string. */
  total_cost_usd: string;
  call_count: number;
  /** Average cost per call in USD as a decimal string. */
  avg_cost_usd: string;
  tokens_saved: number;
  compression_ratio: number;
  shadow_mode: boolean;
}

/** Response shape from GET /v1/attribution. */
export interface AttributionResponse {
  feature_tags: AttributionByTag[];
  /** Aggregate total cost in USD as a decimal string. */
  total_cost_usd: string;
  total_tokens: number;
  /** Cache hit rate in the range [0, 1]. */
  cache_hit_rate: number;
  tokens_saved: number;
}

/** Request body for POST /v1/budgets/{feature_tag} (upsert). */
export interface BudgetPayload {
  /** Budget limit in USD as a decimal string. */
  budget_usd: string;
  /** Budget reset period, e.g. "monthly" or "weekly". */
  period: string;
}

/** A single budget record returned from GET /v1/budgets. */
export interface BudgetStatus {
  feature_tag: string;
  /** Configured budget limit in USD as a decimal string. */
  budget_usd: string;
  period: string;
  /** Amount spent so far in USD as a decimal string. */
  spent_usd: string;
  /** Remaining budget in USD as a decimal string. */
  remaining_usd: string;
  /** Percentage of budget consumed in the range [0, 1+]. */
  pct_used: number;
  /** Alert level: "ok" (< 80%), "warning" (80-100%), "exhausted" (≥ 100%). */
  status: "ok" | "warning" | "exhausted";
}

/** Query parameters for the /v1/spans endpoint. */
export interface SpanQueryParams {
  feature_tag?: string;
  model?: string;
  provider?: string;
  environment?: string;
  from_ts?: string;
  to_ts?: string;
  compression_applied?: boolean;
  limit?: number;
  offset?: number;
}

/** A single inference span record from GET /v1/spans. */
export interface InferenceSpanResponse {
  id: string;
  timestamp: string;
  model: string;
  provider: string;
  input_tokens: number;
  output_tokens: number;
  /** Cost for this span in USD as a decimal string. */
  cost_usd: string;
  feature_tag: string;
  compression_applied: boolean;
  cache_hit: boolean;
  prompt_hash: string;
  artifact_type: string;
  routing_decision: string | null;
  tokens_saved: number;
  batch_eligible: boolean;
}

/** Aggregate cache statistics from GET /v1/cache/stats. */
export interface CacheStats {
  total_lookups: number;
  cache_hits: number;
  /** Cache hit rate in the range [0, 1]. */
  hit_rate: number;
  tokens_saved: number;
  /** Total cost saved by cache hits in USD as a decimal string. */
  cost_saved_usd: string;
}

/** Health check response from GET /health. */
export interface HealthStatus {
  status: string;
  version: string;
}

/** Error detail payload returned by the backend on 4xx/5xx responses. */
export interface TrajectAPIErrorPayload {
  detail: string;
}
