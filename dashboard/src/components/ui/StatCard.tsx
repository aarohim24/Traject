/**
 * StatCard — KPI card with label, value, and optional delta indicator.
 *
 * Styled with bg-gray-800 base, gray-700 border, and a teal accent left border.
 */

import clsx from "clsx";

interface StatCardProps {
  label: string;
  value: string;
  delta?: string;
}

/**
 * Renders a single KPI metric card.
 *
 * @param label - Descriptive label shown above the value.
 * @param value - Primary metric value (pre-formatted string).
 * @param delta - Optional change indicator shown below the value in teal.
 */
export default function StatCard({ label, value, delta }: StatCardProps): JSX.Element {
  return (
    <div
      className={clsx(
        "bg-gray-800 border border-gray-700 border-l-4 border-l-teal-400 rounded-lg p-4",
      )}
    >
      <p className="text-sm text-gray-400">{label}</p>
      <p className="text-2xl font-bold text-gray-100 mt-1">{value}</p>
      {delta && <p className="text-sm text-teal-400 mt-1">{delta}</p>}
    </div>
  );
}
