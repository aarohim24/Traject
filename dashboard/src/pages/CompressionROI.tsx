/**
 * CompressionROI — dashboard page for compression return-on-investment metrics.
 *
 * Shows 4 KPI cards, an area chart of tokens saved over time, a horizontal
 * bar chart of compression ratio by feature_tag, and a line chart of cache
 * hit rate over time.
 */

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import CompressionChart from "../components/ui/CompressionChart";
import StatCard from "../components/ui/StatCard";
import { useAttribution } from "../hooks/useAttribution";
import { COLORS } from "../lib/constants";
import { formatCost, formatPct, formatTokens } from "../lib/formatters";
import { useAppStore } from "../store/appStore";

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

/**
 * CompressionROI page component.
 */
export default function CompressionROI(): JSX.Element {
  const timeRange = useAppStore((s) => s.timeRange);
  const { from_ts, to_ts } = resolveTimeRange(timeRange);

  const { data, isLoading } = useAttribution({ from_ts, to_ts });

  if (isLoading) {
    return (
      <div className="space-y-4 p-6">
        <div className="grid grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="bg-gray-700 rounded-lg h-24 animate-pulse" />
          ))}
        </div>
        <div className="bg-gray-700 rounded-lg h-72 animate-pulse" />
        <div className="bg-gray-700 rounded-lg h-72 animate-pulse" />
      </div>
    );
  }

  const tags = data?.breakdown ?? [];

  // Tokens saved over time — use dimension entries as data points
  const tokensSavedData = tags.map((t) => ({
    name: t.dimension,
    value: t.total_tokens_saved,
  }));

  // Compression ratio by dimension — not sent by the API, derived per row.
  const compressionRatioData = tags.map((t) => ({
    name: t.dimension,
    value:
      t.total_tokens > 0
        ? parseFloat((t.total_tokens_saved / t.total_tokens).toFixed(3))
        : 0,
  }));

  // Cache hit rate series — per-tag rate, not a single value broadcast across all points.
  const cacheHitData = tags.map((t) => ({
    name: t.dimension,
    rate: t.call_count > 0 ? t.cache_hit_count / t.call_count : 0,
  }));

  // Weighted average compression ratio across all tags (by tokens, not a flat mean).
  const totalTokens = tags.reduce((sum, t) => sum + t.total_tokens, 0);
  const totalTokensSaved = tags.reduce((sum, t) => sum + t.total_tokens_saved, 0);
  const avgRatio = totalTokens > 0 ? totalTokensSaved / totalTokens : 0;

  // Real backend-computed estimate, not a rough per-token approximation.
  const estimatedCostSaved = parseFloat(data?.total_savings_usd ?? "0");

  return (
    <div className="p-6 space-y-6">
      {/* KPI Cards */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard
          label="Total Tokens Saved"
          value={formatTokens(totalTokensSaved)}
        />
        <StatCard
          label="Est. Cost Saved"
          value={formatCost(estimatedCostSaved)}
        />
        <StatCard
          label="Avg Compression Ratio"
          value={`${(avgRatio * 100).toFixed(1)}%`}
        />
        <StatCard
          label="Feature Tags Tracked"
          value={`${tags.length}`}
        />
      </div>

      {/* Tokens Saved over time — area chart */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-4">
          Tokens Saved by Feature Tag
        </h2>
        <CompressionChart type="area" data={tokensSavedData} />
      </div>

      {/* Compression Ratio by Feature Tag — horizontal bar */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-4">
          Compression Ratio by Feature Tag
        </h2>
        <CompressionChart type="bar" data={compressionRatioData} />
      </div>

      {/* Cache Hit Rate over time — line chart */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-4">
          Cache Hit Rate
        </h2>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart
            data={cacheHitData}
            margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="name"
              tick={{ fill: "#9ca3af", fontSize: 12 }}
              axisLine={{ stroke: "#374151" }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: "#9ca3af", fontSize: 12 }}
              axisLine={{ stroke: "#374151" }}
              tickLine={false}
              tickFormatter={(v: number) => formatPct(v)}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1f2937",
                border: "1px solid #374151",
                borderRadius: "6px",
                color: "#f3f4f6",
              }}
              formatter={(v: number) => [formatPct(v), "Cache Hit Rate"]}
            />
            <Line
              type="monotone"
              dataKey="rate"
              stroke={COLORS.chartPrimary}
              strokeWidth={2}
              dot={{ fill: COLORS.chartPrimary, r: 4 }}
              name="Cache Hit Rate"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Cumulative cost saved stat */}
      <div className="grid grid-cols-1">
        <StatCard
          label="Cumulative Cost Saved by Semantic Cache"
          value={formatCost(estimatedCostSaved)}
          delta={`Based on ${formatTokens(totalTokensSaved)} tokens saved`}
        />
      </div>
    </div>
  );
}
