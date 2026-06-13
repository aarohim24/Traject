/**
 * SpanExplorer — dashboard page for exploring and filtering inference spans.
 *
 * Provides a filter bar (feature_tag, model, provider, environment,
 * date range, compression_applied) and a paginated SpanTable.
 */

import { useState } from "react";
import type { SpanQueryParams } from "../api/types";
import SpanTable from "../components/ui/SpanTable";
import { useSpans } from "../hooks/useSpans";
import { DEFAULT_PAGE_SIZE } from "../lib/constants";

interface FilterState {
  feature_tag: string;
  model: string;
  provider: string;
  environment: string;
  from_ts: string;
  to_ts: string;
  compression_applied: boolean | undefined;
}

const EMPTY_FILTERS: FilterState = {
  feature_tag: "",
  model: "",
  provider: "",
  environment: "",
  from_ts: "",
  to_ts: "",
  compression_applied: undefined,
};

/** Map non-empty filter fields to the SpanQueryParams shape. */
function buildParams(
  filters: FilterState,
  page: number,
): SpanQueryParams {
  const params: SpanQueryParams = {
    limit: DEFAULT_PAGE_SIZE,
    offset: page * DEFAULT_PAGE_SIZE,
  };
  if (filters.feature_tag) params.feature_tag = filters.feature_tag;
  if (filters.model) params.model = filters.model;
  if (filters.provider) params.provider = filters.provider;
  if (filters.environment) params.environment = filters.environment;
  if (filters.from_ts) params.from_ts = filters.from_ts;
  if (filters.to_ts) params.to_ts = filters.to_ts;
  if (filters.compression_applied !== undefined)
    params.compression_applied = filters.compression_applied;
  return params;
}

/**
 * SpanExplorer page component.
 */
export default function SpanExplorer(): JSX.Element {
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [page, setPage] = useState(0);

  const params = buildParams(appliedFilters, page);
  const { data: spans, isLoading } = useSpans(params);

  function handleFilterChange(
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) {
    const { name, value, type } = e.target;
    if (type === "checkbox") {
      const checked = (e.target as HTMLInputElement).checked;
      setFilters((prev) => ({
        ...prev,
        compression_applied: checked ? true : undefined,
      }));
    } else {
      setFilters((prev) => ({ ...prev, [name]: value }));
    }
  }

  function handleApply(e: React.FormEvent) {
    e.preventDefault();
    setAppliedFilters(filters);
    setPage(0);
  }

  function handleReset() {
    setFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
    setPage(0);
  }

  return (
    <div className="p-6 space-y-6">
      {/* Filter bar */}
      <form
        onSubmit={handleApply}
        className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-4"
      >
        <h2 className="text-sm font-semibold text-gray-400">Filters</h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Feature Tag
            </label>
            <input
              name="feature_tag"
              value={filters.feature_tag}
              onChange={handleFilterChange}
              placeholder="my-feature"
              className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-teal-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Model</label>
            <input
              name="model"
              value={filters.model}
              onChange={handleFilterChange}
              placeholder="gpt-4o"
              className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-teal-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Provider
            </label>
            <input
              name="provider"
              value={filters.provider}
              onChange={handleFilterChange}
              placeholder="openai"
              className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-teal-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Environment
            </label>
            <input
              name="environment"
              value={filters.environment}
              onChange={handleFilterChange}
              placeholder="production"
              className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-teal-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">From</label>
            <input
              name="from_ts"
              type="datetime-local"
              value={filters.from_ts}
              onChange={handleFilterChange}
              className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-teal-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">To</label>
            <input
              name="to_ts"
              type="datetime-local"
              value={filters.to_ts}
              onChange={handleFilterChange}
              className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-teal-400"
            />
          </div>
        </div>

        {/* Compression checkbox */}
        <div className="flex items-center gap-2">
          <input
            id="compression_applied"
            name="compression_applied"
            type="checkbox"
            checked={filters.compression_applied === true}
            onChange={handleFilterChange}
            className="accent-teal-400 w-4 h-4 rounded"
          />
          <label
            htmlFor="compression_applied"
            className="text-sm text-gray-400 select-none"
          >
            Compression applied only
          </label>
        </div>

        <div className="flex gap-2">
          <button
            type="submit"
            className="text-xs bg-teal-500 hover:bg-teal-600 text-gray-950 font-semibold px-4 py-1 rounded transition-colors"
          >
            Apply
          </button>
          <button
            type="button"
            onClick={handleReset}
            className="text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 font-semibold px-4 py-1 rounded transition-colors"
          >
            Reset
          </button>
        </div>
      </form>

      {/* Span table */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-4">Spans</h2>
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="bg-gray-700 rounded h-8 animate-pulse"
              />
            ))}
          </div>
        ) : (
          <SpanTable
            spans={spans ?? []}
            page={page}
            onPageChange={setPage}
          />
        )}
      </div>
    </div>
  );
}
