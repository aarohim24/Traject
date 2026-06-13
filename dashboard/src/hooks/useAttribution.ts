/**
 * useAttribution — TanStack Query wrapper for the /v1/attribution endpoint.
 *
 * Automatically refetches every REFETCH_INTERVAL_MS milliseconds (60 s).
 */

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { AttributionParams, AttributionResponse } from "../api/types";
import { REFETCH_INTERVAL_MS } from "../lib/constants";

/**
 * Fetch cost attribution data grouped by feature_tag.
 *
 * @param params - Date range and optional grouping filters forwarded to the API.
 * @returns TanStack Query result wrapping `AttributionResponse`.
 */
export function useAttribution(params: AttributionParams) {
  return useQuery<AttributionResponse>({
    queryKey: ["attribution", params],
    queryFn: () => apiClient.getAttribution(params),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}
