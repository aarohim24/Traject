/**
 * App — root component. Sets up QueryClientProvider, BrowserRouter, and all page routes.
 *
 * Pages are lazy-loaded via React.lazy to enable code splitting. A Suspense boundary
 * provides a fallback spinner while the chunk loads. All page routes are nested inside
 * the shared <Layout> component which renders the sidebar and header.
 */

import React, { Suspense, lazy } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Layout from "./components/layout/Layout";

const CostOverview = lazy(() => import("./pages/CostOverview"));
const CompressionROI = lazy(() => import("./pages/CompressionROI"));
const BudgetManager = lazy(() => import("./pages/BudgetManager"));
const RouterAnalytics = lazy(() => import("./pages/RouterAnalytics"));
const SpanExplorer = lazy(() => import("./pages/SpanExplorer"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
});

function LoadingFallback(): JSX.Element {
  return (
    <div className="flex items-center justify-center h-screen bg-gray-950">
      <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-teal-400" />
    </div>
  );
}

export default function App(): JSX.Element {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={<LoadingFallback />}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<CostOverview />} />
              <Route path="/compression" element={<CompressionROI />} />
              <Route path="/budgets" element={<BudgetManager />} />
              <Route path="/router" element={<RouterAnalytics />} />
              <Route path="/spans" element={<SpanExplorer />} />
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
