/**
 * BudgetManager.test.tsx — tests for the BudgetManager page component.
 *
 * Mocks the useBudgets hooks to control the data shown in the table.
 * Verifies table rows, status badge colors, and form submission.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BudgetStatus } from "../api/types";

// ---------------------------------------------------------------------------
// Mock the hooks module
// ---------------------------------------------------------------------------

vi.mock("../hooks/useBudgets", () => ({
  useBudgets: vi.fn(),
  useUpsertBudget: vi.fn(),
  useDeleteBudget: vi.fn(),
}));

// Mock recharts to avoid canvas errors in jsdom
vi.mock("recharts", () => {
  const Stub = ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  );
  return {
    ResponsiveContainer: Stub,
    RadialBarChart: Stub,
    RadialBar: Stub,
    PolarAngleAxis: Stub,
    Tooltip: Stub,
    Legend: Stub,
  };
});

import React from "react";
import { useBudgets, useDeleteBudget, useUpsertBudget } from "../hooks/useBudgets";
import BudgetManager from "../pages/BudgetManager";

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

/** Budgets covering all three status thresholds. */
const MOCK_BUDGETS: BudgetStatus[] = [
  {
    feature_tag: "chat",
    budget_usd: "100.00",
    period: "monthly",
    spent_usd: "50.00",
    remaining_usd: "50.00",
    pct_used: 0.5, // 50% → ok (green)
    status: "ok",
  },
  {
    feature_tag: "summarise",
    budget_usd: "200.00",
    period: "weekly",
    spent_usd: "170.00",
    remaining_usd: "30.00",
    pct_used: 0.85, // 85% → warning (yellow)
    status: "warning",
  },
  {
    feature_tag: "embed",
    budget_usd: "50.00",
    period: "daily",
    spent_usd: "60.00",
    remaining_usd: "-10.00",
    pct_used: 1.2, // 120% → exhausted (red)
    status: "exhausted",
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

/** Shared mock mutation object returned by useUpsertBudget / useDeleteBudget. */
function makeMockMutation(mutateFn = vi.fn()) {
  return {
    mutate: mutateFn,
    isPending: false,
  };
}

function renderBudgetManager() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter>
        <BudgetManager />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("BudgetManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    // Default mock state: data loaded, no pending mutations
    (useBudgets as ReturnType<typeof vi.fn>).mockReturnValue({
      data: MOCK_BUDGETS,
      isLoading: false,
    });
    (useUpsertBudget as ReturnType<typeof vi.fn>).mockReturnValue(
      makeMockMutation(),
    );
    (useDeleteBudget as ReturnType<typeof vi.fn>).mockReturnValue(
      makeMockMutation(),
    );
  });

  // -------------------------------------------------------------------------
  // Table rows
  // -------------------------------------------------------------------------

  it("renders a table row for each budget", () => {
    renderBudgetManager();

    // Each feature tag appears in the table cell (font-mono teal) and in the
    // BudgetGauge below — use getAllByText and confirm at least one match each.
    expect(screen.getAllByText("chat").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("summarise").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("embed").length).toBeGreaterThanOrEqual(1);
  });

  it("renders budget amounts and periods in the table", () => {
    renderBudgetManager();

    // Period column (capitalised by CSS but text content is raw)
    expect(screen.getByText("monthly")).toBeInTheDocument();
    expect(screen.getByText("weekly")).toBeInTheDocument();
    expect(screen.getByText("daily")).toBeInTheDocument();
  });

  it("shows empty state message when there are no budgets", () => {
    (useBudgets as ReturnType<typeof vi.fn>).mockReturnValue({
      data: [],
      isLoading: false,
    });

    renderBudgetManager();

    expect(
      screen.getByText("No budgets configured. Add one above."),
    ).toBeInTheDocument();
  });

  it("shows loading skeleton while data is fetching", () => {
    (useBudgets as ReturnType<typeof vi.fn>).mockReturnValue({
      data: undefined,
      isLoading: true,
    });

    renderBudgetManager();

    const skeletons = document.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  // -------------------------------------------------------------------------
  // Status badge colors
  // -------------------------------------------------------------------------

  it("applies text-green-400 to 'ok' status badge", () => {
    renderBudgetManager();

    // The status cell for 'chat' (ok) should have green colour class
    const okBadge = screen.getByText("ok");
    expect(okBadge).toHaveClass("text-green-400");
  });

  it("applies text-yellow-400 to 'warning' status badge", () => {
    renderBudgetManager();

    const warningBadge = screen.getByText("warning");
    expect(warningBadge).toHaveClass("text-yellow-400");
  });

  it("applies text-red-400 to 'exhausted' status badge", () => {
    renderBudgetManager();

    const exhaustedBadge = screen.getByText("exhausted");
    expect(exhaustedBadge).toHaveClass("text-red-400");
  });

  // -------------------------------------------------------------------------
  // Add budget form submission
  // -------------------------------------------------------------------------

  it("shows the add-budget form when '+ Add Budget' button is clicked", () => {
    renderBudgetManager();

    const addButton = screen.getByRole("button", { name: /\+ Add Budget/i });
    fireEvent.click(addButton);

    // Form inputs are identifiable by placeholder text (labels lack htmlFor)
    expect(screen.getByPlaceholderText("my-feature")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("100.00")).toBeInTheDocument();
    // Period select
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("calls upsertBudget with form values on submit", async () => {
    const mutateFn = vi.fn((_args: unknown, options?: { onSuccess?: () => void }) => {
      // Simulate success callback
      options?.onSuccess?.();
    });

    (useUpsertBudget as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: mutateFn,
      isPending: false,
    });

    renderBudgetManager();

    // Open the form
    fireEvent.click(screen.getByRole("button", { name: /\+ Add Budget/i }));

    // Fill in the form using placeholder text
    const featureTagInput = screen.getByPlaceholderText("my-feature");
    const budgetInput = screen.getByPlaceholderText("100.00");
    const periodSelect = screen.getByRole("combobox");

    fireEvent.change(featureTagInput, { target: { value: "new-feature" } });
    fireEvent.change(budgetInput, { target: { value: "250" } });
    fireEvent.change(periodSelect, { target: { value: "weekly" } });

    // Submit the form
    fireEvent.submit(screen.getByRole("button", { name: /Save/i }).closest("form")!);

    await waitFor(() => {
      expect(mutateFn).toHaveBeenCalledTimes(1);
      expect(mutateFn).toHaveBeenCalledWith(
        {
          featureTag: "new-feature",
          payload: { budget_usd: "250", period: "weekly" },
        },
        expect.objectContaining({ onSuccess: expect.any(Function) }),
      );
    });
  });

  it("hides the form after successful submission", async () => {
    const mutateFn = vi.fn((_args: unknown, options?: { onSuccess?: () => void }) => {
      options?.onSuccess?.();
    });

    (useUpsertBudget as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: mutateFn,
      isPending: false,
    });

    renderBudgetManager();

    fireEvent.click(screen.getByRole("button", { name: /\+ Add Budget/i }));
    expect(screen.getByPlaceholderText("my-feature")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("my-feature"), {
      target: { value: "temp", name: "feature_tag" },
    });
    fireEvent.change(screen.getByPlaceholderText("100.00"), {
      target: { value: "10", name: "budget_usd" },
    });

    fireEvent.submit(screen.getByRole("button", { name: /Save/i }).closest("form")!);

    await waitFor(() => {
      // Form should be hidden after success
      expect(screen.queryByPlaceholderText("my-feature")).not.toBeInTheDocument();
    });
  });
});
