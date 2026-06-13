/**
 * BudgetManager — dashboard page for viewing and managing feature-tag budgets.
 *
 * Displays a table of all budgets with status badges, an inline add form,
 * inline delete confirmation, and one BudgetGauge per budget below the table.
 */

import clsx from "clsx";
import { useState } from "react";
import type { BudgetStatus } from "../api/types";
import BudgetGauge from "../components/ui/BudgetGauge";
import StatCard from "../components/ui/StatCard";
import {
  useBudgets,
  useDeleteBudget,
  useUpsertBudget,
} from "../hooks/useBudgets";
import { formatCost, formatPct } from "../lib/formatters";

/** Return Tailwind colour class based on pct_used. */
function statusColor(status: BudgetStatus["status"]): string {
  switch (status) {
    case "ok":
      return "text-green-400";
    case "warning":
      return "text-yellow-400";
    case "exhausted":
      return "text-red-400";
  }
}

interface AddFormState {
  feature_tag: string;
  budget_usd: string;
  period: string;
}

const EMPTY_FORM: AddFormState = {
  feature_tag: "",
  budget_usd: "",
  period: "monthly",
};

/**
 * BudgetManager page component.
 */
export default function BudgetManager(): JSX.Element {
  const { data: budgets, isLoading } = useBudgets();
  const upsert = useUpsertBudget();
  const remove = useDeleteBudget();

  const [form, setForm] = useState<AddFormState>(EMPTY_FORM);
  const [showForm, setShowForm] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  function handleFormChange(
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    upsert.mutate(
      {
        featureTag: form.feature_tag,
        payload: { budget_usd: form.budget_usd, period: form.period },
      },
      {
        onSuccess: () => {
          setForm(EMPTY_FORM);
          setShowForm(false);
        },
      },
    );
  }

  function handleDelete(featureTag: string) {
    remove.mutate(featureTag, {
      onSuccess: () => setConfirmDelete(null),
    });
  }

  if (isLoading) {
    return (
      <div className="space-y-4 p-6">
        <div className="bg-gray-700 rounded-lg h-48 animate-pulse" />
        <div className="bg-gray-700 rounded-lg h-24 animate-pulse" />
      </div>
    );
  }

  const rows = budgets ?? [];
  const totalBudget = rows.reduce((s, b) => s + parseFloat(b.budget_usd), 0);
  const totalSpent = rows.reduce((s, b) => s + parseFloat(b.spent_usd), 0);

  return (
    <div className="p-6 space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
        <StatCard label="Total Budget" value={formatCost(totalBudget)} />
        <StatCard label="Total Spent" value={formatCost(totalSpent)} />
        <StatCard
          label="Active Budgets"
          value={rows.length.toString()}
        />
      </div>

      {/* Budget table */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-400">Budgets</h2>
          <button
            onClick={() => setShowForm((prev) => !prev)}
            className="text-xs bg-teal-500 hover:bg-teal-600 text-gray-950 font-semibold px-3 py-1 rounded transition-colors"
          >
            {showForm ? "Cancel" : "+ Add Budget"}
          </button>
        </div>

        {/* Inline add form */}
        {showForm && (
          <form
            onSubmit={handleSubmit}
            className="grid grid-cols-3 gap-3 mb-4 p-3 bg-gray-700/50 rounded-lg"
          >
            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Feature Tag
              </label>
              <input
                name="feature_tag"
                value={form.feature_tag}
                onChange={handleFormChange}
                required
                placeholder="my-feature"
                className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-teal-400"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Budget (USD)
              </label>
              <input
                name="budget_usd"
                value={form.budget_usd}
                onChange={handleFormChange}
                required
                type="number"
                min="0"
                step="0.01"
                placeholder="100.00"
                className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-teal-400"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Period
              </label>
              <select
                name="period"
                value={form.period}
                onChange={handleFormChange}
                className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-teal-400"
              >
                <option value="monthly">Monthly</option>
                <option value="weekly">Weekly</option>
                <option value="daily">Daily</option>
              </select>
            </div>
            <div className="col-span-3 flex justify-end gap-2 mt-1">
              <button
                type="submit"
                disabled={upsert.isPending}
                className="text-xs bg-teal-500 hover:bg-teal-600 disabled:opacity-50 text-gray-950 font-semibold px-4 py-1 rounded transition-colors"
              >
                {upsert.isPending ? "Saving…" : "Save"}
              </button>
            </div>
          </form>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-sm text-gray-300">
            <thead>
              <tr className="border-b border-gray-700 text-gray-400 text-xs uppercase tracking-wide">
                <th className="text-left py-2 px-3">Feature Tag</th>
                <th className="text-left py-2 px-3">Budget</th>
                <th className="text-left py-2 px-3">Period</th>
                <th className="text-left py-2 px-3">Spent</th>
                <th className="text-left py-2 px-3">Remaining</th>
                <th className="text-left py-2 px-3">Used</th>
                <th className="text-left py-2 px-3">Status</th>
                <th className="py-2 px-3" />
              </tr>
            </thead>
            <tbody>
              {rows.map((budget) => (
                <>
                  <tr
                    key={budget.feature_tag}
                    className="border-b border-gray-700/50 hover:bg-gray-700/30"
                  >
                    <td className="py-2 px-3 font-mono text-teal-400">
                      {budget.feature_tag}
                    </td>
                    <td className="py-2 px-3">
                      {formatCost(budget.budget_usd)}
                    </td>
                    <td className="py-2 px-3 capitalize">{budget.period}</td>
                    <td className="py-2 px-3">
                      {formatCost(budget.spent_usd)}
                    </td>
                    <td className="py-2 px-3">
                      {formatCost(budget.remaining_usd)}
                    </td>
                    <td className="py-2 px-3">
                      {formatPct(budget.pct_used)}
                    </td>
                    <td
                      className={clsx(
                        "py-2 px-3 font-semibold capitalize",
                        statusColor(budget.status),
                      )}
                    >
                      {budget.status}
                    </td>
                    <td className="py-2 px-3 text-right">
                      <button
                        onClick={() =>
                          setConfirmDelete(
                            confirmDelete === budget.feature_tag
                              ? null
                              : budget.feature_tag,
                          )
                        }
                        className="text-xs text-red-400 hover:text-red-300 transition-colors"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                  {/* Inline delete confirmation row */}
                  {confirmDelete === budget.feature_tag && (
                    <tr
                      key={`${budget.feature_tag}-confirm`}
                      className="bg-red-900/20"
                    >
                      <td
                        colSpan={8}
                        className="py-2 px-3 text-sm text-red-300"
                      >
                        Delete budget for{" "}
                        <span className="font-mono">{budget.feature_tag}</span>?{" "}
                        <button
                          onClick={() => handleDelete(budget.feature_tag)}
                          disabled={remove.isPending}
                          className="text-red-400 hover:text-red-200 font-semibold disabled:opacity-50"
                        >
                          {remove.isPending ? "Deleting…" : "Confirm"}
                        </button>{" "}
                        ·{" "}
                        <button
                          onClick={() => setConfirmDelete(null)}
                          className="text-gray-400 hover:text-gray-200"
                        >
                          Cancel
                        </button>
                      </td>
                    </tr>
                  )}
                </>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-gray-500">
                    No budgets configured. Add one above.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Budget gauges */}
      {rows.length > 0 && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-400 mb-4">
            Budget Utilisation
          </h2>
          <div className="flex flex-wrap gap-6">
            {rows.map((budget) => (
              <BudgetGauge
                key={budget.feature_tag}
                featureTag={budget.feature_tag}
                pctUsed={budget.pct_used}
                status={budget.status}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
