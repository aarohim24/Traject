/**
 * Layout — root shell component shared by all dashboard pages.
 *
 * Arranges the Sidebar (left) and a main column (right) that contains
 * the Header at the top and the current page content via <Outlet />.
 * The outermost div uses bg-gray-950 as the page background.
 */

import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import Header from "./Header";

export default function Layout(): JSX.Element {
  return (
    <div className="flex bg-gray-950 min-h-screen">
      {/* Left navigation */}
      <Sidebar />

      {/* Main area: header + page content */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
