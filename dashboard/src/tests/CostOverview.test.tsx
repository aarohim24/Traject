/**
 * CostOverview.test.tsx — tests for the CostOverview page component.
 *
 * Mocks the useAttribution hook to isolate rendering from network calls.
 * Verifies stat cards, loading skeleton, and time-range selector behaviour.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AttributionResponse } from "../api/types";
import type { TIME_RANGES } from "../lib/constants";

// ---------------------------------------------------------------------------
// Mock the useAttribution hook so tests never hit the network
// ---------------------------------------------------------------------------

vi.mock("../hooks/useAttribution", () => ({
  useAttribution: vi.fn(),
}));

import { useAttribution } from "../hooks/useAttribution";

// Also mock recharts to avoid canvas-related errors in jsdom
vi.mock("recharts", () => {
  // Return minimal stubs for every recharts export used in CostOverview
  const Stub = ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  );
  return {
    ResponsiveContainer: Stub,
    LineChart: Stub,
    BarChart: Stub,
    PieChart: Stub,
    Bar: Stub,
    Line: Stub,
    Pie: Stub,
    Cell: Stub,
    CartesianGrid: Stub,
    XAxis: Stub,
    YAxis: Stub,
    Tooltip: Stub,
    Legend: Stub,
  };
});

import React from "react";
import CostOverview from "../pages/CostOverview";
import Header from "../components/layout/Header";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a QueryClient with retries disabled for fast tests. */
function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

/** Sample attribution response returned when data is available. */
const MOCK_ATTRIBUTION: AttributionResponse = {
  total_cost_usd: "12.345678",
  total_tokens: 1234567,
  cache_hit_rate: 0.72,
  tokens_saved: 50000,
  feature_tags: [
    {
      feature_tag: "chat",
      total_cost_usd: "5.000000",
      call_count: 100,
      avg_cost_usd: "0.050000",
      tokens_saved: 1000,
      compression_ratio: 0.8,
      shadow_mode: false,
    },
    {
      feature_tag: "summarise",
      total_cost_usd: "7.345678",
      call_count: 50,
      avg_cost_usd: "0.146913",
      tokens_saved: 2000,
      compression_ratio: 0.65,
      shadow_mode: false,
    },
  ],
};

/** Render CostOverview wrapped in the minimal required providers. */
function renderCostOverview() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <CostOverview />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CostOverview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading skeleton while data is fetching", () => {
    // Mock useAttribution to return isLoading: true
    (useAttribution as ReturnType<typeof vi.fn>).mockReturnValue({
      data: undefined,
      isLoading: true,
    });

    renderCostOverview();

    // The skeleton uses animate-pulse — check at least one element is present
    const skeletons = document.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("renders 4 stat cards when data is loaded", () => {
    (useAttribution as ReturnType<typeof vi.fn>).mockReturnValue({
      data: MOCK_ATTRIBUTION,
      isLoading: false,
    });

    renderCostOverview();

    // "Total Cost" appears in both the StatCard label and the table column header —
    // assert there are at least 1 StatCard-style <p> elements with that text.
    const totalCostEls = screen.getAllByText("Total Cost");
    expect(totalCostEls.length).toBeGreaterThanOrEqual(1);
    // The others are unique
    expect(screen.getByText("Total Tokens")).toBeInTheDocument();
    expect(screen.getByText("Cache Hit Rate")).toBeInTheDocument();
    expect(screen.getByText("Tokens Saved")).toBeInTheDocument();
  });

  it("displays correct formatted values in stat cards", () => {
    (useAttribution as ReturnType<typeof vi.fn>).mockReturnValue({
      data: MOCK_ATTRIBUTION,
      isLoading: false,
    });

    renderCostOverview();

    // Total cost $12.35 (≥1.0 → 2 decimal places)
    expect(screen.getByText("$12.35")).toBeInTheDocument();
    // Total tokens 1,234,567
    expect(screen.getByText("1,234,567")).toBeInTheDocument();
    // Cache hit rate 72.0%
    expect(screen.getByText("72.0%")).toBeInTheDocument();
    // Tokens saved 50,000
    expect(screen.getByText("50,000")).toBeInTheDocument();
  });

  it("renders the top feature tags table when data is loaded", () => {
    (useAttribution as ReturnType<typeof vi.fn>).mockReturnValue({
      data: MOCK_ATTRIBUTION,
      isLoading: false,
    });

    renderCostOverview();

    expect(screen.getByText("chat")).toBeInTheDocument();
    expect(screen.getByText("summarise")).toBeInTheDocument();
  });

  it("shows empty table message when feature_tags is empty", () => {
    (useAttribution as ReturnType<typeof vi.fn>).mockReturnValue({
      data: { ...MOCK_ATTRIBUTION, feature_tags: [] },
      isLoading: false,
    });

    renderCostOverview();

    expect(
      screen.getByText("No data for the selected time range."),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Header — time-range selector (3 options)
// ---------------------------------------------------------------------------

describe("Header time-range selector", () => {
  it("renders exactly 3 time-range buttons (24h, 7d, 30d)", () => {
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter initialEntries={["/"]}>
          <Header />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // TIME_RANGES = ["24h", "7d", "30d"]
    const btn24h = screen.getByRole("button", { name: /set time range to 24h/i });
    const btn7d = screen.getByRole("button", { name: /set time range to 7d/i });
    const btn30d = screen.getByRole("button", { name: /set time range to 30d/i });

    expect(btn24h).toBeInTheDocument();
    expect(btn7d).toBeInTheDocument();
    expect(btn30d).toBeInTheDocument();
  });

  it("shows 3 time-range options total", () => {
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter initialEntries={["/"]}>
          <Header />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const timeRangeButtons = screen.getAllByRole("button", {
      name: /set time range to/i,
    });
    expect(timeRangeButtons).toHaveLength(3);
  });
});
