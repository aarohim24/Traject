/**
 * Sidebar — fixed left navigation panel for the Traject dashboard.
 *
 * Renders NavLinks to all five dashboard pages using React Router.
 * The active link is highlighted with the teal-400 accent colour;
 * inactive links use gray-400.
 */

import {
  DollarSign,
  TrendingDown,
  Target,
  Shuffle,
  Search,
  Trophy,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { NavLink } from "react-router-dom";

interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
}

const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "Cost Overview", icon: DollarSign },
  { path: "/compression", label: "Compression ROI", icon: TrendingDown },
  { path: "/budgets", label: "Budget Manager", icon: Target },
  { path: "/router", label: "Router Analytics", icon: Shuffle },
  { path: "/spans", label: "Span Explorer", icon: Search },
  { path: "/benchmarks", label: "Benchmarks", icon: Trophy },
];

export default function Sidebar(): JSX.Element {
  return (
    <aside className="bg-gray-900 border-r border-gray-700 h-screen w-64 flex flex-col flex-shrink-0">
      {/* Logo / brand */}
      <div className="flex items-center gap-2 px-6 py-5 border-b border-gray-700">
        <Zap className="h-5 w-5 text-teal-400" aria-hidden="true" />
        <span className="text-teal-400 text-xl font-bold tracking-tight">Traject</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map(({ path, label, icon: Icon }) => (
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
            <Icon className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-gray-700">
        <p className="text-xs text-gray-600">Traject v0.4.0</p>
      </div>
    </aside>
  );
}
