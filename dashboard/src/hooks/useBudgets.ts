/**
 * useBudgets — TanStack Query hooks for the /v1/budgets endpoint.
 *
 * Provides a query for listing all budgets plus mutations for upsert
 * and delete, both with automatic query invalidation on success.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { BudgetPayload } from "../api/types";

/**
 * Fetch all budget records from the backend.
 *
 * @returns TanStack Query result wrapping `BudgetStatus[]`.
 */
export function useBudgets() {
  return useQuery({
    queryKey: ["budgets"],
    queryFn: () => apiClient.getBudgets(),
  });
}

/**
 * Mutation for creating or updating a budget for a given feature_tag.
 *
 * Invalidates the `["budgets"]` query on success so the table refreshes.
 *
 * @returns TanStack Mutation result for upsertBudget.
 */
export function useUpsertBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      featureTag,
      payload,
    }: {
      featureTag: string;
      payload: BudgetPayload;
    }) => apiClient.upsertBudget(featureTag, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["budgets"] }),
  });
}

/**
 * Mutation for deleting a budget by feature_tag.
 *
 * Invalidates the `["budgets"]` query on success so the table refreshes.
 *
 * @returns TanStack Mutation result for deleteBudget.
 */
export function useDeleteBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (featureTag: string) => apiClient.deleteBudget(featureTag),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["budgets"] }),
  });
}
