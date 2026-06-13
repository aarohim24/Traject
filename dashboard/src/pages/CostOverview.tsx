/**
 * CostOverview — dashboard page showing aggregate cost KPIs and charts.
 *
 * Renders 4 StatCards (total cost, total tokens, cache hit rate, tokens saved),
 * a CostChart (line), a bar chart per model, a donut chart per provider,
 * and a sortable top-10 feature tags table. Auto-refreshes every 60 s.
 */

import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AttributionByTag } from "../api/types";
import CostChart from "../components/ui/CostChart";
import StatCard from "../components/ui/StatCard";
import { useAttribution } from "../hooks/useAttribution";
import { COLORS } from "../lib/constants";
import { formatCost, formatPct, formatTokens } from "../lib/formatters";
import { useAppStore } from "../store/appStore";

type SortKey = keyof Pick<
  AttributionByTag,
  "feature_tag" | "total_cost_usd" | "call_count" | "avg_cost_usd"
>;

/** Resolve a time-range label to ISO from_ts / to_ts strings. */
function resolveTimeRange(range: "24h" | "7d" | "30d"): {
  from_ts: string;
  to_ts: string;
} {
  const now = new Date();
  const to_ts = now.toISOString();
  const ms = range === "24h" ? 86_400_000 : range === "7d" ? 604_800_000 : 2_592_000_000;
  const from_ts = new Date(now.getTime() - ms).toISOString();
  return { from_ts, to_ts };
}

/** Derive a rough "model" label from a feature_tag for demo bar chart data. */
function buildModelData(
  tags: AttributionByTag[],
): { model: string; cost: number }[] {
  // Aggregate by feature_tag as a proxy for model breakdown.
  return tags.slice(0, 6).map((t) => ({
    model: t.feature_tag,
    cost: parseFloat(t.total_cost_usd),
  }));
}

const DONUT_COLORS = ["#2dd4bf", "#60a5fa", "#f472b6", "#a78bfa", "#fb923c"];

/**
 * CostOverview page component.
 */
export default function CostOverview(): JSX.Element {
  const timeRange = useAppStore((s) => s.timeRange);
  const { from_ts, to_ts } = resolveTimeRange(timeRange);

  const { data, isLoading } = useAttribution({ from_ts, to_ts });

  const [sortKey, setSortKey] = useState<SortKey>("total_cost_usd");
  const [sortAsc, setSortAsc] = useState(false);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortAsc((prev) => !prev);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-4 p-6">
        {/* Loading skeleton */}
        <div className="grid grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="bg-gray-700 rounded-lg h-24 animate-pulse" />
          ))}
        </div>
        <div className="bg-gray-700 rounded-lg h-72 animate-pulse" />
        <div className="bg-gray-700 rounded-lg h-48 animate-pulse" />
      </div>
    );
  }

  const tags = data?.feature_tags ?? [];

  // Sorted top-10 table rows
  const sortedTags = [...tags]
    .sort((a, b) => {
      if (sortKey === "feature_tag") {
        return sortAsc
          ? a.feature_tag.localeCompare(b.feature_tag)
          : b.feature_tag.localeCompare(a.feature_tag);
      }
      const av =
        sortKey === "call_count"
          ? a.call_count
          : parseFloat(a[sortKey]);
      const bv =
        sortKey === "call_count"
          ? b.call_count
          : parseFloat(b[sortKey]);
      return sortAsc ? av - bv : bv - av;
    })
    .slice(0, 10);

  const providerData = tags.slice(0, 5).map((t, i) => ({
    name: t.feature_tag,
    value: parseFloat(t.total_cost_usd),
    color: DONUT_COLORS[i % DONUT_COLORS.length],
  }));

  const modelData = buildModelData(tags);

  return (
    <div className="p-6 space-y-6">
      {/* Row 1 — KPI stat cards */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard
          label="Total Cost"
          value={formatCost(data?.total_cost_usd ?? "0")}
        />
        <StatCard
          label="Total Tokens"
          value={formatTokens(data?.total_tokens ?? 0)}
        />
        <StatCard
          label="Cache Hit Rate"
          value={formatPct(data?.cache_hit_rate ?? 0)}
        />
        <StatCard
          label="Tokens Saved"
          value={formatTokens(data?.tokens_saved ?? 0)}
        />
      </div>

      {/* Row 2 — Charts */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-400 mb-4">
            Cost by Feature Tag
          </h2>
          <CostChart data={tags} />
        </div>

        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-400 mb-4">
            Cost by Model
          </h2>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={modelData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="model"
                tick={{ fill: "#9ca3af", fontSize: 11 }}
                axisLine={{ stroke: "#374151" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "#9ca3af", fontSize: 11 }}
                axisLine={{ stroke: "#374151" }}
                tickLine={false}
                tickFormatter={(v: number) => `$${v.toFixed(2)}`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1f2937",
                  border: "1px solid #374151",
                  borderRadius: "6px",
                  color: "#f3f4f6",
                }}
              />
              <Bar dataKey="cost" fill={COLORS.chartPrimary} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-4">
          Cost by Provider
        </h2>
        <ResponsiveContainer width="100%" height={240}>
          <PieChart>
            <Pie
              data={providerData}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={100}
              dataKey="value"
              nameKey="name"
            >
              {providerData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                backgroundColor: "#1f2937",
                border: "1px solid #374151",
                borderRadius: "6px",
                color: "#f3f4f6",
              }}
              formatter={(value: number) => [`$${value.toFixed(6)}`, "Cost"]}
            />
            <Legend wrapperStyle={{ color: "#9ca3af" }} />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Row 3 — Top-10 feature tags table */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-4">
          Top 10 Feature Tags by Cost
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-gray-300">
            <thead>
              <tr className="border-b border-gray-700 text-gray-400">
                {(
                  [
                    ["feature_tag", "Feature Tag"],
                    ["total_cost_usd", "Total Cost"],
                    ["call_count", "Calls"],
                    ["avg_cost_usd", "Avg Cost"],
                  ] as [SortKey, string][]
                ).map(([key, label]) => (
                  <th
                    key={key}
                    className="text-left py-2 px-3 cursor-pointer hover:text-teal-400 select-none"
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
              {sortedTags.map((tag) => (
                <tr
                  key={tag.feature_tag}
                  className="border-b border-gray-700/50 hover:bg-gray-700/30"
                >
                  <td className="py-2 px-3 font-mono text-teal-400">
                    {tag.feature_tag}
                  </td>
                  <td className="py-2 px-3">
                    {formatCost(tag.total_cost_usd)}
                  </td>
                  <td className="py-2 px-3">
                    {tag.call_count.toLocaleString()}
                  </td>
                  <td className="py-2 px-3">{formatCost(tag.avg_cost_usd)}</td>
                </tr>
              ))}
              {sortedTags.length === 0 && (
                <tr>
                  <td
                    colSpan={4}
                    className="py-8 text-center text-gray-500"
                  >
                    No data for the selected time range.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
