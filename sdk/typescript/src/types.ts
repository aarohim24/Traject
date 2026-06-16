/**
 * Core type definitions for the Traject TypeScript SDK.
 *
 * Mirrors the canonical Python InferenceSpan model and supporting types
 * defined in `sdk/python/traject/models.py` and
 * `sdk/python/traject/classifier/artifact_type.py`. All types are pure
 * interfaces and type aliases — no logic lives here.
 */

/**
 * Artifact type classification for a message or span.
 *
 * Mirrors the Python `ArtifactType` StrEnum with the same string values,
 * ensuring cross-SDK consistency in cost attribution and telemetry.
 */
export type ArtifactType =
  | "system_prompt"
  | "user_message"
  | "assistant_message"
  | "tool_call"
  | "tool_result"
  | "rag_chunk"
  | "few_shot_example"
  | "reasoning_block"
  | "unknown";

/**
 * Token usage breakdown for a single LLM call.
 *
 * Matches the usage fields surfaced by provider response objects
 * (ADR-002: token counts from provider response headers).
 */
export interface UsageData {
  /** Number of prompt/input tokens consumed (>= 0). */
  inputTokens: number;
  /** Number of completion/output tokens generated (>= 0). */
  outputTokens: number;
  /** Number of tokens served from the provider cache (>= 0), if available. */
  cachedTokens?: number;
  /** Total tokens (inputTokens + outputTokens). */
  totalTokens: number;
}

/**
 * Immutable record of a single instrumented LLM API call.
 *
 * TypeScript mirror of the Python `InferenceSpan` Pydantic model. Every
 * field is populated by the instrumentor immediately after the provider
 * response is received. Spans are emitted to the configured exporter and
 * are never mutated after creation.
 *
 * Monetary values are represented as strings to avoid IEEE 754 float
 * precision loss (ADR-006 equivalent for TypeScript).
 */
export interface InferenceSpan {
  /** Unique identifier for this span (UUID v4 hex string). */
  spanId: string;
  /** Trace identifier grouping related spans across agent boundaries. */
  traceId?: string;
  /** Session identifier for grouping spans within a user session. */
  sessionId?: string;
  /** Model identifier as returned by the provider response. */
  model: string;
  /** Provider name (e.g. `"openai"`, `"anthropic"`). */
  provider: string;
  /** UTC ISO 8601 timestamp at which the instrumented call started. */
  startTime: string;
  /** UTC ISO 8601 timestamp at which the instrumented call completed. */
  endTime: string;
  /** Elapsed time of the provider call in milliseconds (>= 0). */
  durationMs: number;
  /** Token usage breakdown for this call. */
  usage: UsageData;
  /**
   * Calculated USD cost as a fixed-point string with 8 decimal places
   * (e.g. `"0.00250000"`), or `null` for unknown models.
   * String representation avoids floating-point precision loss (ADR-006).
   */
  costUsd?: string;
  /**
   * SHA-256 hex digest of the normalized prompt content (64 lowercase hex
   * characters). Raw prompt text is never stored (ADR-005).
   */
  promptHash?: string;
  /** Logical grouping label for cost attribution. */
  featureTag?: string;
  /** Classified artifact type of the primary message. */
  artifactType?: ArtifactType;
  /** Arbitrary key-value metadata attached at instrumentation time. */
  metadata?: Record<string, unknown>;
}

/**
 * Configuration options for the Traject TypeScript SDK.
 *
 * All fields are optional. The SDK operates in console-only export mode
 * when neither `backendUrl` nor `exportToConsole` is explicitly set.
 */
export interface TrajectConfig {
  /**
   * Traject backend API key for authenticated span ingestion.
   * Traject never reads, stores, or logs provider API keys — only its own
   * backend key (ADR standards).
   */
  apiKey?: string;
  /**
   * Base URL of the Traject backend service (e.g. `"http://localhost:8000"`).
   * When set, spans are POSTed to `{backendUrl}/v1/spans`.
   */
  backendUrl?: string;
  /**
   * When `true`, each emitted span is written as JSON to stdout.
   * Useful for local development and debugging.
   */
  exportToConsole?: boolean;
  /** Logical grouping label applied to all spans emitted in this session. */
  featureTag?: string;
}
