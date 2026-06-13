/**
 * RouterDecisionTable — sortable table of inference span routing decisions.
 *
 * Columns: timestamp, model, routing_decision, artifact_type, cost_usd.
 * Clicking a column header toggles ascending/descending sort.
 * When routing_decision is null, displays "(no routing)".
 */

import { useState } from "react";
import type { InferenceSpanResponse } from "../../api/types";
import { formatCost } from "../../lib/formatters";

type SortKey = "timestamp" | "model" | "routing_decision" | "artifact_type" | "cost_usd";

interface RouterDecisionTableProps {
  /** Array of inference span records to render. */
  data: InferenceSpanResponse[];
}

/**
 * Renders a sortable table of router decisions extracted from span data.
 *
 * @param data - Inference spans to display.
 */
export default function RouterDecisionTable({
  data,
}: RouterDecisionTableProps): JSX.Element {
  const [sortKey, setSortKey] = useState<SortKey>("timestamp");
  const [sortAsc, setSortAsc] = useState(false);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortAsc((prev) => !prev);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  }

  const sorted = [...data].sort((a, b) => {
    const av = a[sortKey] ?? "";
    const bv = b[sortKey] ?? "";
    const cmp =
      typeof av === "string" && typeof bv === "string"
        ? av.localeCompare(bv)
        : String(av).localeCompare(String(bv));
    return sortAsc ? cmp : -cmp;
  });

  const columns: { key: SortKey; label: string }[] = [
    { key: "timestamp", label: "Timestamp" },
    { key: "model", label: "Model" },
    { key: "routing_decision", label: "Routing Decision" },
    { key: "artifact_type", label: "Artifact Type" },
    { key: "cost_usd", label: "Cost (USD)" },
  ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm text-gray-300">
        <thead>
          <tr className="border-b border-gray-700 text-gray-400 text-xs uppercase tracking-wide">
            {columns.map(({ key, label }) => (
              <th
                key={key}
                className="text-left py-2 px-3 cursor-pointer hover:text-teal-400 select-none whitespace-nowrap"
                onClick={() => toggleSort(key)}
              >
                {label}
                {sortKey === key && (
                  <span className="ml-1">{sortAsc ? "↑" : "↓"}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((span) => (
            <tr
              key={span.id}
              className="border-b border-gray-700/50 hover:bg-gray-700/30"
            >
              <td className="py-2 px-3 text-xs text-gray-400 whitespace-nowrap">
                {new Date(span.timestamp).toLocaleString()}
              </td>
              <td className="py-2 px-3 font-mono text-teal-400 whitespace-nowrap">
                {span.model}
              </td>
              <td className="py-2 px-3">
                {span.routing_decision ?? (
                  <span className="text-gray-500 italic">(no routing)</span>
                )}
              </td>
              <td className="py-2 px-3">{span.artifact_type}</td>
              <td className="py-2 px-3">{formatCost(span.cost_usd)}</td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={5} className="py-8 text-center text-gray-500">
                No routing data for the selected filters.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
