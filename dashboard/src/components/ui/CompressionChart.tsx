/**
 * CompressionChart — dual-mode chart for compression analytics.
 *
 * "area" mode renders a Recharts AreaChart with teal fill and stroke.
 * "bar"  mode renders a horizontal BarChart (layout="vertical") with teal fill.
 */

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { COLORS } from "../../lib/constants";

interface CompressionChartEntry {
  name: string;
  value: number;
}

interface CompressionChartProps {
  /** Chart variant. "area" for time-series, "bar" for category comparison. */
  type: "area" | "bar";
  /** Data points to render. */
  data: CompressionChartEntry[];
}

/**
 * Renders either an area or horizontal bar chart for compression metrics.
 *
 * @param type - "area" for area chart, "bar" for horizontal bar chart.
 * @param data - Array of { name, value } entries.
 */
export default function CompressionChart({
  type,
  data,
}: CompressionChartProps): JSX.Element {
  const tooltipStyle = {
    contentStyle: {
      backgroundColor: "#1f2937",
      border: "1px solid #374151",
      borderRadius: "6px",
      color: "#f3f4f6",
    },
  };

  if (type === "area") {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
          <defs>
            <linearGradient id="compressionGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS.chartPrimary} stopOpacity={0.3} />
              <stop offset="95%" stopColor={COLORS.chartPrimary} stopOpacity={0} />
            </linearGradient>
          </defs>
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
          />
          <Tooltip {...tooltipStyle} />
          <Area
            type="monotone"
            dataKey="value"
            stroke={COLORS.chartPrimary}
            strokeWidth={2}
            fill="url(#compressionGradient)"
            name="Tokens Saved"
          />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart
        layout="vertical"
        data={data}
        margin={{ top: 8, right: 16, left: 64, bottom: 8 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" horizontal={false} />
        <XAxis
          type="number"
          tick={{ fill: "#9ca3af", fontSize: 12 }}
          axisLine={{ stroke: "#374151" }}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fill: "#9ca3af", fontSize: 11 }}
          axisLine={{ stroke: "#374151" }}
          tickLine={false}
          width={60}
        />
        <Tooltip {...tooltipStyle} />
        <Bar
          dataKey="value"
          fill={COLORS.chartPrimary}
          radius={[0, 4, 4, 0]}
          name="Compression Ratio"
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
