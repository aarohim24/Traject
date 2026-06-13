/**
 * RouterAnalytics — dashboard page for model routing analytics.
 *
 * Shows a RouterDecisionTable, a PieChart for model distribution,
 * a StatCard for total cost, and a BarChart for artifact_type counts.
 */

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
import RouterDecisionTable from "../components/ui/RouterDecisionTable";
import StatCard from "../components/ui/StatCard";
import { useSpans } from "../hooks/useSpans";
import { useAppStore } from "../store/appStore";
import { formatCost } from "../lib/formatters";

/** Resolve a time-range label to ISO from_ts / to_ts strings. */
function resolveTimeRange(range: "24h" | "7d" | "30d"): {
  from_ts: string;
  to_ts: string;
} {
  const now = new Date();
  const to_ts = now.toISOString();
  const ms =
    range === "24h" ? 86_400_000 : range === "7d" ? 604_800_000 : 2_592_000_000;
  const from_ts = new Date(now.getTime() - ms).toISOString();
  return { from_ts, to_ts };
}

const DONUT_COLORS = ["#2dd4bf", "#60a5fa", "#f472b6", "#a78bfa", "#fb923c", "#34d399"];

/**
 * RouterAnalytics page component.
 */
export default function RouterAnalytics(): JSX.Element {
  const timeRange = useAppStore((s) => s.timeRange);
  const { from_ts, to_ts } = resolveTimeRange(timeRange);

  const { data: spans, isLoading } = useSpans({ from_ts, to_ts, limit: 200 });

  if (isLoading) {
    return (
      <div className="space-y-4 p-6">
        <div className="bg-gray-700 rounded-lg h-24 animate-pulse" />
        <div className="bg-gray-700 rounded-lg h-72 animate-pulse" />
        <div className="bg-gray-700 rounded-lg h-64 animate-pulse" />
      </div>
    );
  }

  const rows = spans ?? [];

  // Total cost across all spans
  const totalCost = rows.reduce((sum, s) => sum + parseFloat(s.cost_usd), 0);

  // Model distribution — count spans per model
  const modelCounts: Record<string, number> = {};
  for (const span of rows) {
    modelCounts[span.model] = (modelCounts[span.model] ?? 0) + 1;
  }
  const modelData = Object.entries(modelCounts).map(([model, count]) => ({
    name: model,
    value: count,
  }));

  // Artifact type counts
  const artifactCounts: Record<string, number> = {};
  for (const span of rows) {
    artifactCounts[span.artifact_type] =
      (artifactCounts[span.artifact_type] ?? 0) + 1;
  }
  const artifactData = Object.entries(artifactCounts).map(
    ([type, count]) => ({ type, count }),
  );

  return (
    <div className="p-6 space-y-6">
      {/* Total cost stat card */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard label="Total Cost (Spans)" value={formatCost(totalCost)} />
        <StatCard label="Total Spans" value={rows.length.toLocaleString()} />
        <StatCard
          label="Routed Spans"
          value={rows
            .filter((s) => s.routing_decision !== null)
            .length.toLocaleString()}
        />
      </div>

      {/* Routing decisions table */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-4">
          Routing Decisions
        </h2>
        <RouterDecisionTable data={rows} />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Model distribution donut */}
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-400 mb-4">
            Model Distribution
          </h2>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={modelData}
                cx="50%"
                cy="50%"
                innerRadius={55}
                outerRadius={90}
                dataKey="value"
                nameKey="name"
              >
                {modelData.map((_entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={DONUT_COLORS[index % DONUT_COLORS.length]}
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1f2937",
                  border: "1px solid #374151",
                  borderRadius: "6px",
                  color: "#f3f4f6",
                }}
              />
              <Legend wrapperStyle={{ color: "#9ca3af" }} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Artifact type bar chart */}
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-400 mb-4">
            Artifact Type Breakdown
          </h2>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={artifactData}
              margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="type"
                tick={{ fill: "#9ca3af", fontSize: 11 }}
                axisLine={{ stroke: "#374151" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "#9ca3af", fontSize: 11 }}
                axisLine={{ stroke: "#374151" }}
                tickLine={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1f2937",
                  border: "1px solid #374151",
                  borderRadius: "6px",
                  color: "#f3f4f6",
                }}
              />
              <Bar dataKey="count" fill="#2dd4bf" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
