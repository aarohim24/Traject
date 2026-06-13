/**
 * SpanTable — paginated, expandable table of inference spans.
 *
 * Displays DEFAULT_PAGE_SIZE rows per page. Clicking a row expands it
 * to reveal additional fields: prompt_hash, artifact_type, routing_decision,
 * tokens_saved, batch_eligible.
 */

import { useState } from "react";
import type { InferenceSpanResponse } from "../../api/types";
import { DEFAULT_PAGE_SIZE } from "../../lib/constants";
import { formatCost } from "../../lib/formatters";

interface SpanTableProps {
  /** Full list of spans for the current filter/page window. */
  spans: InferenceSpanResponse[];
  /** Current page index (0-based). */
  page: number;
  /** Callback invoked when the user navigates to a different page. */
  onPageChange: (p: number) => void;
}

/**
 * Paginated span table with row expansion.
 *
 * @param spans        - Spans to render for the current page window.
 * @param page         - Current 0-based page index.
 * @param onPageChange - Called with the new page index when navigation occurs.
 */
export default function SpanTable({
  spans,
  page,
  onPageChange,
}: SpanTableProps): JSX.Element {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const pageStart = page * DEFAULT_PAGE_SIZE;
  const pageRows = spans.slice(pageStart, pageStart + DEFAULT_PAGE_SIZE);
  const totalPages = Math.max(1, Math.ceil(spans.length / DEFAULT_PAGE_SIZE));

  function toggleExpand(id: string) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-gray-300">
          <thead>
            <tr className="border-b border-gray-700 text-gray-400 text-xs uppercase tracking-wide">
              <th className="text-left py-2 px-3 whitespace-nowrap">Timestamp</th>
              <th className="text-left py-2 px-3 whitespace-nowrap">Model</th>
              <th className="text-right py-2 px-3 whitespace-nowrap">In Tokens</th>
              <th className="text-right py-2 px-3 whitespace-nowrap">Out Tokens</th>
              <th className="text-right py-2 px-3 whitespace-nowrap">Cost</th>
              <th className="text-left py-2 px-3 whitespace-nowrap">Feature Tag</th>
              <th className="text-center py-2 px-3 whitespace-nowrap">Compressed</th>
              <th className="text-center py-2 px-3 whitespace-nowrap">Cache Hit</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((span) => (
              <>
                <tr
                  key={span.id}
                  className="border-b border-gray-700/50 hover:bg-gray-700/30 cursor-pointer"
                  onClick={() => toggleExpand(span.id)}
                >
                  <td className="py-2 px-3 text-xs text-gray-400 whitespace-nowrap">
                    {new Date(span.timestamp).toLocaleString()}
                  </td>
                  <td className="py-2 px-3 font-mono text-teal-400 whitespace-nowrap">
                    {span.model}
                  </td>
                  <td className="py-2 px-3 text-right">
                    {span.input_tokens.toLocaleString()}
                  </td>
                  <td className="py-2 px-3 text-right">
                    {span.output_tokens.toLocaleString()}
                  </td>
                  <td className="py-2 px-3 text-right">
                    {formatCost(span.cost_usd)}
                  </td>
                  <td className="py-2 px-3 text-xs text-gray-400">
                    {span.feature_tag}
                  </td>
                  <td className="py-2 px-3 text-center">
                    {span.compression_applied ? (
                      <span className="text-teal-400">✓</span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="py-2 px-3 text-center">
                    {span.cache_hit ? (
                      <span className="text-green-400">✓</span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                </tr>
                {/* Expanded detail row */}
                {expandedId === span.id && (
                  <tr
                    key={`${span.id}-expanded`}
                    className="bg-gray-900/60 border-b border-gray-700"
                  >
                    <td colSpan={8} className="py-3 px-6">
                      <dl className="grid grid-cols-2 gap-x-8 gap-y-1 text-xs md:grid-cols-3 lg:grid-cols-5">
                        <div>
                          <dt className="text-gray-500 uppercase tracking-wide">
                            Prompt Hash
                          </dt>
                          <dd className="font-mono text-gray-300 truncate max-w-[12ch]">
                            {span.prompt_hash}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-gray-500 uppercase tracking-wide">
                            Artifact Type
                          </dt>
                          <dd className="text-gray-300">{span.artifact_type}</dd>
                        </div>
                        <div>
                          <dt className="text-gray-500 uppercase tracking-wide">
                            Routing Decision
                          </dt>
                          <dd className="text-gray-300">
                            {span.routing_decision ?? (
                              <span className="italic text-gray-500">
                                (no routing)
                              </span>
                            )}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-gray-500 uppercase tracking-wide">
                            Tokens Saved
                          </dt>
                          <dd className="text-gray-300">
                            {span.tokens_saved.toLocaleString()}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-gray-500 uppercase tracking-wide">
                            Batch Eligible
                          </dt>
                          <dd
                            className={
                              span.batch_eligible
                                ? "text-teal-400"
                                : "text-gray-500"
                            }
                          >
                            {span.batch_eligible ? "Yes" : "No"}
                          </dd>
                        </div>
                      </dl>
                    </td>
                  </tr>
                )}
              </>
            ))}
            {pageRows.length === 0 && (
              <tr>
                <td colSpan={8} className="py-8 text-center text-gray-500">
                  No spans match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination controls */}
      <div className="flex items-center justify-between text-sm text-gray-400 pt-1">
        <span>
          Page {page + 1} of {totalPages} &mdash;{" "}
          {spans.length.toLocaleString()} spans
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page === 0}
            className="px-3 py-1 bg-gray-700 rounded hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ← Prev
          </button>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages - 1}
            className="px-3 py-1 bg-gray-700 rounded hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
}
