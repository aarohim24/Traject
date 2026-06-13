/**
 * BudgetGauge — Recharts RadialBarChart showing budget utilisation percentage.
 *
 * Color is determined by status:
 *   ok         → green  (#4ade80)
 *   warning    → yellow (#facc15)
 *   exhausted  → red    (#f87171)
 */

import {
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
} from "recharts";

interface BudgetGaugeProps {
  /** Feature tag label displayed below the gauge. */
  featureTag: string;
  /** Percentage of budget consumed expressed as a value in [0, 1+]. */
  pctUsed: number;
  /** Alert status from the backend. */
  status: "ok" | "warning" | "exhausted";
}

const STATUS_COLOR: Record<"ok" | "warning" | "exhausted", string> = {
  ok: "#4ade80",
  warning: "#facc15",
  exhausted: "#f87171",
};

/**
 * Renders a radial bar gauge for a single budget entry.
 *
 * @param featureTag - The feature tag this budget belongs to.
 * @param pctUsed    - Fraction consumed; 1.0 = 100%.
 * @param status     - Current alert status for colour selection.
 */
export default function BudgetGauge({
  featureTag,
  pctUsed,
  status,
}: BudgetGaugeProps): JSX.Element {
  const fill = STATUS_COLOR[status];
  // RadialBarChart uses 0–100 numeric domain.
  const displayPct = Math.min(pctUsed * 100, 100);

  const chartData = [
    { name: featureTag, value: displayPct, fill },
  ];

  return (
    <div className="flex flex-col items-center">
      <div className="relative w-24 h-24">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            cx="50%"
            cy="50%"
            innerRadius="60%"
            outerRadius="100%"
            barSize={10}
            data={chartData}
            startAngle={90}
            endAngle={-270}
          >
            <PolarAngleAxis
              type="number"
              domain={[0, 100]}
              angleAxisId={0}
              tick={false}
            />
            <RadialBar
              background={{ fill: "#374151" }}
              dataKey="value"
              cornerRadius={4}
              // fill is set per-entry via chartData
            />
          </RadialBarChart>
        </ResponsiveContainer>
        {/* Centered percentage text */}
        <span
          className="absolute inset-0 flex items-center justify-center text-xs font-bold"
          style={{ color: fill }}
        >
          {`${(pctUsed * 100).toFixed(0)}%`}
        </span>
      </div>
      <span className="mt-1 text-xs text-gray-400 text-center max-w-[6rem] truncate">
        {featureTag}
      </span>
    </div>
  );
}
