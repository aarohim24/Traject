/**
 * useSpans — TanStack Query wrapper for the /v1/spans endpoint.
 *
 * Accepts filter and pagination params that are forwarded directly
 * to the API client. Results are keyed on the full params object so
 * any filter change triggers a fresh fetch.
 */

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { SpanQueryParams } from "../api/types";

/**
 * Fetch a filtered, paginated list of inference spans.
 *
 * @param params - Filter and pagination options forwarded to GET /v1/spans.
 * @returns TanStack Query result wrapping `InferenceSpanResponse[]`.
 */
export function useSpans(params: SpanQueryParams) {
  return useQuery({
    queryKey: ["spans", params],
    queryFn: () => apiClient.getSpans(params),
  });
}
