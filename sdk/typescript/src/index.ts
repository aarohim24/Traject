/**
 * Traject TypeScript SDK — public entry point.
 *
 * Re-exports all public API symbols. Import from `@traject-sdk/typescript`
 * (or the local package root) to access instrumentation, cost calculation,
 * and span emission utilities.
 *
 * @example
 * ```ts
 * import { configure, patch, calculateCost } from "@traject-sdk/typescript";
 *
 * configure({ exportToConsole: true });
 * patch(openaiClient);
 * ```
 */

export type { ArtifactType, UsageData, InferenceSpan, TrajectConfig } from "./types";
export type { ModelPricing } from "./pricing";
export { PRICING } from "./pricing";
export { calculateCost } from "./cost_calculator";
export { SpanEmitter } from "./span_emitter";
export {
  instrument,
  patch,
  setGlobalConfig,
  getGlobalConfig,
} from "./instrumentor";

import type { TrajectConfig } from "./types";
import { setGlobalConfig } from "./instrumentor";

/**
 * Configure the Traject SDK globally.
 *
 * Equivalent to calling {@link setGlobalConfig}. All subsequent
 * instrumented calls will use this configuration unless overridden
 * locally at the call site.
 *
 * @param config - SDK configuration to apply globally.
 */
export function configure(config: TrajectConfig): void {
  setGlobalConfig(config);
}
