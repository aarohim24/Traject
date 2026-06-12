/**
 * Span emitter for the Axon TypeScript SDK.
 *
 * Handles console export (synchronous) and backend POST (fire-and-forget)
 * of {@link InferenceSpan} records. Errors from the backend POST are logged
 * but never thrown — the emitter never disrupts application code.
 */

import type { AxonConfig, InferenceSpan } from "./types";

/**
 * Emits {@link InferenceSpan} records to configured outputs.
 *
 * Instantiate once per configured session and reuse across calls.
 */
export class SpanEmitter {
  private readonly config: AxonConfig;

  /**
   * Create a SpanEmitter.
   *
   * @param config - Axon SDK configuration controlling export behaviour.
   */
  constructor(config: AxonConfig) {
    this.config = config;
  }

  /**
   * Emit a span to all configured outputs.
   *
   * Console export is synchronous. Backend POST is fire-and-forget;
   * errors are logged to `console.error` but never thrown.
   *
   * @param span - The {@link InferenceSpan} to emit.
   */
  emit(span: InferenceSpan): void {
    if (this.config.exportToConsole === true) {
      console.log(JSON.stringify(span, null, 2)); // eslint-disable-line no-console
    }

    if (
      this.config.backendUrl !== undefined &&
      this.config.backendUrl !== ""
    ) {
      const url = `${this.config.backendUrl}/v1/spans`;
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (this.config.apiKey !== undefined && this.config.apiKey !== "") {
        headers["X-Axon-API-Key"] = this.config.apiKey;
      }
      // Fire-and-forget: errors are logged, never thrown.
      void Promise.resolve()
        .then(() =>
          fetch(url, {
            method: "POST",
            headers,
            body: JSON.stringify(span),
          }),
        )
        .catch((err: unknown) => {
          console.error("[axon] Failed to POST span to backend:", err); // eslint-disable-line no-console
        });
    }
  }
}
