/**
 * Sidebar — fixed left navigation panel for the Axon dashboard.
 *
 * Renders NavLinks to all five dashboard pages using React Router.
 * The active link is highlighted with the teal-400 accent colour;
 * inactive links use gray-400.
 */

import { NavLink } from "react-router-dom";

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "Cost Overview", icon: "💰" },
  { path: "/compression", label: "Compression ROI", icon: "📉" },
  { path: "/budgets", label: "Budget Manager", icon: "🎯" },
  { path: "/router", label: "Router Analytics", icon: "🔀" },
  { path: "/spans", label: "Span Explorer", icon: "🔍" },
  { path: "/benchmarks", label: "Benchmarks", icon: "🏆" },
];

export default function Sidebar(): JSX.Element {
  return (
    <aside className="bg-gray-900 border-r border-gray-700 h-screen w-64 flex flex-col flex-shrink-0">
      {/* Logo / brand */}
      <div className="flex items-center gap-2 px-6 py-5 border-b border-gray-700">
        <span className="text-teal-400 text-xl font-bold tracking-tight">⚡ Axon</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map(({ path, label, icon }) => (
          <NavLink
            key={path}
            to={path}
            end={path === "/"}
            className={({ isActive }) =>
              [
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                isActive
                  ? "text-teal-400 bg-gray-800"
                  : "text-gray-400 hover:text-gray-100 hover:bg-gray-800",
              ].join(" ")
            }
          >
            <span className="text-base">{icon}</span>
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-gray-700">
        <p className="text-xs text-gray-600">Axon v0.4.0</p>
      </div>
    </aside>
  );
}
