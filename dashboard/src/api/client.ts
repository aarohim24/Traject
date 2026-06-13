/**
 * client — typed HTTP client for the Axon backend REST API.
 *
 * Exports `AxonAPIError`, `AxonAPIClient`, and a pre-configured singleton
 * `apiClient` resolved from Vite environment variables. All methods throw
 * `AxonAPIError` on non-2xx responses. The `X-Axon-API-Key` header is
 * added automatically to every request by the private `request` helper.
 */

import type {
  AttributionParams,
  AttributionResponse,
  AxonAPIErrorPayload,
  BudgetPayload,
  BudgetStatus,
  CacheStats,
  HealthStatus,
  InferenceSpanResponse,
  SpanQueryParams,
} from "./types";

// ---------------------------------------------------------------------------
// Error class
// ---------------------------------------------------------------------------

/**
 * Thrown by `AxonAPIClient` whenever the backend returns a non-2xx status.
 * Callers can inspect `error.status` to decide how to handle the failure.
 */
export class AxonAPIError extends Error {
  constructor(
    /** HTTP status code returned by the backend. */
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "AxonAPIError";
  }
}

// ---------------------------------------------------------------------------
// Client class
// ---------------------------------------------------------------------------

/**
 * Type-safe HTTP client for the Axon backend API.
 *
 * Construct with a base URL and an API key, then call the typed methods.
 * Use the exported `apiClient` singleton for normal application code.
 */
export class AxonAPIClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;

  constructor(baseUrl: string, apiKey: string) {
    // Normalise: strip trailing slash so path concatenation is always clean.
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.apiKey = apiKey;
  }

  // -------------------------------------------------------------------------
  // Private request helper
  // -------------------------------------------------------------------------

  /**
   * Execute a fetch request against the backend.
   *
   * Automatically injects the `X-Axon-API-Key` header. Parses the response
   * body as JSON and returns it as `T`. Throws `AxonAPIError` on any non-2xx
   * status code, using the `detail` field from the error payload when present.
   */
  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "X-Axon-API-Key": this.apiKey,
      // Merge any caller-supplied headers, allowing overrides (except key).
      ...(options?.headers as Record<string, string> | undefined),
    };

    const response = await fetch(url, { ...options, headers });

    if (!response.ok) {
      // Attempt to extract the FastAPI error detail; fall back gracefully.
      let message = `HTTP ${response.status}`;
      try {
        const payload = (await response.json()) as AxonAPIErrorPayload;
        if (payload.detail) {
          message = payload.detail;
        }
      } catch {
        // Response body was not JSON — keep the default message.
      }
      throw new AxonAPIError(response.status, message);
    }

    // 204 No Content — return void cast to T (callers annotate as Promise<void>).
    if (response.status === 204) {
      return undefined as unknown as T; // safe: callers use Promise<void>
    }

    return response.json() as Promise<T>;
  }

  // -------------------------------------------------------------------------
  // Attribution
  // -------------------------------------------------------------------------

  /**
   * Fetch cost attribution data grouped by feature_tag.
   *
   * @param params - Optional date range and grouping filters.
   */
  async getAttribution(params: AttributionParams): Promise<AttributionResponse> {
    const query = buildQuery(params as QueryParams);
    return this.request<AttributionResponse>(`/v1/attribution${query}`);
  }

  // -------------------------------------------------------------------------
  // Budgets
  // -------------------------------------------------------------------------

  /**
   * Retrieve all budget records across every feature_tag.
   */
  async getBudgets(): Promise<BudgetStatus[]> {
    return this.request<BudgetStatus[]>("/v1/budgets");
  }

  /**
   * Retrieve the budget record for a single feature_tag.
   *
   * @param featureTag - The feature tag to look up.
   */
  async getBudget(featureTag: string): Promise<BudgetStatus> {
    return this.request<BudgetStatus>(`/v1/budgets/${encodeURIComponent(featureTag)}`);
  }

  /**
   * Create or update the budget for a feature_tag.
   *
   * @param featureTag - The feature tag to configure.
   * @param payload    - Budget limit and period.
   */
  async upsertBudget(featureTag: string, payload: BudgetPayload): Promise<BudgetStatus> {
    return this.request<BudgetStatus>(`/v1/budgets/${encodeURIComponent(featureTag)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /**
   * Delete the budget configuration for a feature_tag.
   *
   * @param featureTag - The feature tag whose budget to remove.
   */
  async deleteBudget(featureTag: string): Promise<void> {
    return this.request<void>(`/v1/budgets/${encodeURIComponent(featureTag)}`, {
      method: "DELETE",
    });
  }

  // -------------------------------------------------------------------------
  // Spans
  // -------------------------------------------------------------------------

  /**
   * Query inference spans with optional filtering and pagination.
   *
   * @param params - Filter and pagination options.
   */
  async getSpans(params: SpanQueryParams): Promise<InferenceSpanResponse[]> {
    const query = buildQuery(params as QueryParams);
    return this.request<InferenceSpanResponse[]>(`/v1/spans${query}`);
  }

  // -------------------------------------------------------------------------
  // Cache stats
  // -------------------------------------------------------------------------

  /**
   * Retrieve aggregate semantic cache statistics.
   *
   * @param featureTag - When provided, scopes stats to that tag only.
   */
  async getCacheStats(featureTag?: string): Promise<CacheStats> {
    const query = featureTag
      ? `?feature_tag=${encodeURIComponent(featureTag)}`
      : "";
    return this.request<CacheStats>(`/v1/cache/stats${query}`);
  }

  // -------------------------------------------------------------------------
  // Health
  // -------------------------------------------------------------------------

  /**
   * Check backend health and retrieve the current version.
   */
  async getHealth(): Promise<HealthStatus> {
    return this.request<HealthStatus>("/health");
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Alias for query-params objects after the typed interfaces are cast.
 * Using `unknown` values because we only call `String()` on them.
 */
type QueryParams = Record<string, unknown>;

/**
 * Serialise a plain params object to a URL query string.
 * Omits keys whose value is `undefined` or `null`.
 */
function buildQuery(params: QueryParams): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null,
  );
  if (entries.length === 0) return "";
  const qs = entries
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
  return `?${qs}`;
}

// ---------------------------------------------------------------------------
// Singleton export
// ---------------------------------------------------------------------------

/**
 * Pre-configured `AxonAPIClient` instance for use throughout the application.
 *
 * Resolved from Vite environment variables at module load time:
 * - `VITE_AXON_BACKEND_URL` — defaults to `http://localhost:8000`
 * - `VITE_AXON_API_KEY`     — defaults to empty string (unauthenticated)
 */
export const apiClient = new AxonAPIClient(
  import.meta.env.VITE_AXON_BACKEND_URL ?? "http://localhost:8000",
  import.meta.env.VITE_AXON_API_KEY ?? "",
);
