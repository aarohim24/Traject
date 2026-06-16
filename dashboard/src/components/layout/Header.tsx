/**
 * Header — top bar displayed on every page of the Traject dashboard.
 *
 * Shows the current page title derived from the active route path and
 * provides a three-button time-range selector (24h / 7d / 30d) that
 * writes the selected value into the global Zustand store.
 */

import { useLocation } from "react-router-dom";
import { useAppStore } from "../../store/appStore";
import { TIME_RANGES } from "../../lib/constants";

/** Maps route paths to human-readable page titles. */
const PAGE_TITLES: Record<string, string> = {
  "/": "Cost Overview",
  "/compression": "Compression ROI",
  "/budgets": "Budget Manager",
  "/router": "Router Analytics",
  "/spans": "Span Explorer",
};

type TimeRange = (typeof TIME_RANGES)[number];

export default function Header(): JSX.Element {
  const { pathname } = useLocation();
  const timeRange = useAppStore((s) => s.timeRange);
  const setTimeRange = useAppStore((s) => s.setTimeRange);

  const title = PAGE_TITLES[pathname] ?? "Traject Dashboard";

  return (
    <header className="bg-gray-900 border-b border-gray-700 px-6 py-4 flex items-center justify-between flex-shrink-0">
      {/* Page title */}
      <h1 className="text-gray-100 text-lg font-semibold">{title}</h1>

      {/* Time-range selector */}
      <div className="flex items-center gap-1 rounded-lg bg-gray-800 p-1">
        {TIME_RANGES.map((range) => {
          const isActive = timeRange === range;
          return (
            <button
              key={range}
              type="button"
              onClick={() => setTimeRange(range as TimeRange)}
              className={[
                "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                isActive
                  ? "bg-teal-500 text-gray-950"
                  : "bg-transparent text-gray-400 hover:text-gray-100",
              ].join(" ")}
              aria-pressed={isActive}
              aria-label={`Set time range to ${range}`}
            >
              {range}
            </button>
          );
        })}
      </div>
    </header>
  );
}
