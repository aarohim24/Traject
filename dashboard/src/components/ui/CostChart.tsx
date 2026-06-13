/**
 * CostChart — Recharts LineChart showing cost by feature_tag.
 *
 * Renders one Line per feature_tag entry using the teal-400 accent colour.
 * Wrapped in a ResponsiveContainer so it fills its parent's width.
 */

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { COLORS } from "../../lib/constants";

interface CostChartEntry {
  feature_tag: string;
  total_cost_usd: string;
  call_count: number;
}

interface CostChartProps {
  /** Array of per-feature-tag attribution entries to visualise. */
  data: CostChartEntry[];
}

/**
 * Line chart visualising total cost (USD) per feature_tag.
 *
 * Each entry in `data` becomes a single labelled data point on the x-axis.
 * A single Line traces total_cost_usd across all feature tags.
 *
 * @param data - Attribution rows from the /v1/attribution response.
 */
export default function CostChart({ data }: CostChartProps): JSX.Element {
  // Recharts expects numeric Y values; parse the string cost here for display only.
  const chartData = data.map((entry) => ({
    name: entry.feature_tag,
    cost: parseFloat(entry.total_cost_usd),
    calls: entry.call_count,
  }));

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart
        data={chartData}
        margin={{ top: 8, right: 24, left: 0, bottom: 8 }}
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
          tickFormatter={(v: number) => `$${v.toFixed(4)}`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#1f2937",
            border: "1px solid #374151",
            borderRadius: "6px",
            color: "#f3f4f6",
          }}
          formatter={(value: number) => [`$${value.toFixed(6)}`, "Cost (USD)"]}
        />
        <Legend wrapperStyle={{ color: "#9ca3af" }} />
        <Line
          type="monotone"
          dataKey="cost"
          stroke={COLORS.chartPrimary}
          strokeWidth={2}
          dot={{ fill: COLORS.chartPrimary, r: 4 }}
          activeDot={{ r: 6 }}
          name="Cost (USD)"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
