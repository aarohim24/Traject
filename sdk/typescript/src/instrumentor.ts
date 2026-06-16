/**
 * Instrumentor for the Traject TypeScript SDK.
 *
 * Provides two instrumentation strategies:
 * - `patch(client)` — wraps an OpenAI or Anthropic client in place.
 * - `instrument(config)` — decorator factory for async functions.
 *
 * Global configuration is managed via `setGlobalConfig` / `getGlobalConfig`.
 * Original errors always propagate to the caller unchanged.
 */

import { randomUUID } from "crypto";
import { calculateCost } from "./cost_calculator";
import { SpanEmitter } from "./span_emitter";
import type { TrajectConfig, InferenceSpan, UsageData } from "./types";

// ---------------------------------------------------------------------------
// Global configuration
// ---------------------------------------------------------------------------

/** Module-level global config set by {@link setGlobalConfig}. */
let _globalConfig: TrajectConfig = {};

/**
 * Set the global Traject SDK configuration.
 *
 * @param config - Configuration to apply globally.
 */
export function setGlobalConfig(config: TrajectConfig): void {
  _globalConfig = config;
}

/**
 * Get the current global Traject SDK configuration.
 *
 * @returns The active global {@link TrajectConfig}.
 */
export function getGlobalConfig(): TrajectConfig {
  return _globalConfig;
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

/** Format a Date as a UTC ISO 8601 string. */
function toIso(ms: number): string {
  return new Date(ms).toISOString();
}

// ---------------------------------------------------------------------------
// instrument() — decorator factory
// ---------------------------------------------------------------------------

/**
 * Decorator factory that wraps an async function to emit an
 * {@link InferenceSpan} on each successful call.
 *
 * Original errors always propagate unchanged — no span is emitted on error.
 *
 * @param config - Optional config override; falls back to global config.
 * @returns A decorator that wraps async functions.
 *
 * @example
 * ```ts
 * const wrappedFn = instrument({ exportToConsole: true })(myAsyncFn);
 * ```
 */
export function instrument(
  config?: TrajectConfig,
): <T extends (...args: unknown[]) => Promise<unknown>>(target: T) => T {
  const effectiveConfig = config ?? _globalConfig;

  return function <T extends (...args: unknown[]) => Promise<unknown>>(
    target: T,
  ): T {
    const wrapped = async function (
      ...args: Parameters<T>
    ): Promise<Awaited<ReturnType<T>>> {
      const startMs = Date.now();
      // Errors propagate unchanged — no try/catch around the original call.
      const result = await (
        target as (...args: unknown[]) => Promise<unknown>
      )(...args);
      const endMs = Date.now();

      const emitter = new SpanEmitter(effectiveConfig);
      const usage: UsageData = {
        inputTokens: 0,
        outputTokens: 0,
        totalTokens: 0,
      };
      const span: InferenceSpan = {
        spanId: randomUUID(),
        model: "unknown",
        provider: "unknown",
        startTime: toIso(startMs),
        endTime: toIso(endMs),
        durationMs: endMs - startMs,
        usage,
      };
      emitter.emit(span);
      return result as Awaited<ReturnType<T>>;
    };
    return wrapped as T;
  };
}

// ---------------------------------------------------------------------------
// patch() — monkey-patch OpenAI / Anthropic clients
// ---------------------------------------------------------------------------

/**
 * OpenAI usage shape from the response object.
 * @internal
 */
interface OpenAIUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
}

/**
 * Anthropic usage shape from the response object.
 * @internal
 */
interface AnthropicUsage {
  input_tokens?: number;
  output_tokens?: number;
}

/**
 * Patch an OpenAI or Anthropic client to wrap its LLM method in place.
 *
 * Detection:
 * - OpenAI: `client.chat.completions.create` exists.
 * - Anthropic: `client.messages.create` exists.
 *
 * The wrapped method returns the original response unchanged. Original
 * errors propagate to the caller — no span is emitted on error.
 *
 * @param client - An OpenAI or Anthropic client instance.
 * @param config - Optional config override; falls back to global config.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function patch(client: unknown, config?: TrajectConfig): void {
  const effectiveConfig = config ?? _globalConfig;
  const emitter = new SpanEmitter(effectiveConfig);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = client as any;

  if (
    c?.chat?.completions?.create !== undefined &&
    typeof c.chat.completions.create === "function"
  ) {
    // OpenAI-style client
    // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
    const originalCreate = c.chat.completions.create.bind(
      // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
      c.chat.completions,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ) as (...args: any[]) => Promise<any>;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
    c.chat.completions.create = async function (
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ...args: any[]
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ): Promise<any> {
      const startMs = Date.now();
      // Errors propagate unchanged.
      // eslint-disable-next-line @typescript-eslint/no-unsafe-call
      const response = await originalCreate(...args);
      const endMs = Date.now();

      // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
      const rawUsage = (response as any)?.usage as OpenAIUsage | undefined;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
      const model: string =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
        typeof (args[0] as any)?.model === "string"
          ? // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
            (args[0] as any).model
          : "unknown";

      const inputTokens = rawUsage?.prompt_tokens ?? 0;
      const outputTokens = rawUsage?.completion_tokens ?? 0;
      const totalTokens = rawUsage?.total_tokens ?? inputTokens + outputTokens;

      const costUsd =
        rawUsage !== undefined
          ? (calculateCost(model, inputTokens, outputTokens) ?? undefined)
          : undefined;

      const usage: UsageData = { inputTokens, outputTokens, totalTokens };
      const span: InferenceSpan = {
        spanId: randomUUID(),
        model,
        provider: "openai",
        startTime: toIso(startMs),
        endTime: toIso(endMs),
        durationMs: endMs - startMs,
        usage,
        costUsd,
      };
      emitter.emit(span);
      return response;
    };
  } else if (
    c?.messages?.create !== undefined &&
    typeof c.messages.create === "function"
  ) {
    // Anthropic-style client
    // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
    const originalCreate = c.messages.create.bind(
      // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
      c.messages,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ) as (...args: any[]) => Promise<any>;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
    c.messages.create = async function (
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ...args: any[]
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ): Promise<any> {
      const startMs = Date.now();
      // eslint-disable-next-line @typescript-eslint/no-unsafe-call
      const response = await originalCreate(...args);
      const endMs = Date.now();

      // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
      const rawUsage = (response as any)?.usage as AnthropicUsage | undefined;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
      const model: string =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
        typeof (args[0] as any)?.model === "string"
          ? // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
            (args[0] as any).model
          : "unknown";

      const inputTokens = rawUsage?.input_tokens ?? 0;
      const outputTokens = rawUsage?.output_tokens ?? 0;

      const costUsd =
        rawUsage !== undefined
          ? (calculateCost(model, inputTokens, outputTokens) ?? undefined)
          : undefined;

      const usage: UsageData = {
        inputTokens,
        outputTokens,
        totalTokens: inputTokens + outputTokens,
      };
      const span: InferenceSpan = {
        spanId: randomUUID(),
        model,
        provider: "anthropic",
        startTime: toIso(startMs),
        endTime: toIso(endMs),
        durationMs: endMs - startMs,
        usage,
        costUsd,
      };
      emitter.emit(span);
      return response;
    };
  }
}
