/**
 * BenchmarkRegistry — public page showing community-submitted benchmark data.
 *
 * Accessible without authentication. Fetches records from GET /v1/benchmarks
 * without including an X-Traject-API-Key header. Displays a sortable table when
 * records exist; shows an empty-state message when no data is available.
 */

import { useEffect, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BenchmarkRecord {
  id: string;
  sdk_version: string;
  python_version: string;
  sample_count: number;
  p50_cost_usd: string;
  p95_cost_usd: string;
  p50_compression_ratio: number;
  p95_compression_ratio: number;
  avg_routing_accuracy: number;
  submitted_at: string;
}

// ---------------------------------------------------------------------------
// Hook — fetch benchmarks without auth
// ---------------------------------------------------------------------------

function useBenchmarks(): {
  records: BenchmarkRecord[];
  isLoading: boolean;
  error: string | null;
} {
  const [records, setRecords] = useState<BenchmarkRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const baseUrl =
      (import.meta.env.VITE_TRAJECT_BACKEND_URL as string | undefined) ??
      "http://localhost:8000";

    // Deliberately no X-Traject-API-Key header — this is a public endpoint
    fetch(`${baseUrl}/v1/benchmarks?limit=50`)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        return res.json() as Promise<BenchmarkRecord[]>;
      })
      .then((data) => {
        setRecords(data);
        setIsLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load benchmarks");
        setIsLoading(false);
      });
  }, []);

  return { records, isLoading, error };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function formatPct(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function BenchmarkRegistry(): JSX.Element {
  const { records, isLoading, error } = useBenchmarks();

  return (
    <div className="p-6 space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-xl font-semibold text-gray-100">
          Community Benchmark Registry
        </h1>
        <p className="mt-1 text-sm text-gray-400">
          Aggregate performance metrics submitted by opted-in Traject deployments.
          No personally-identifiable information is collected.
        </p>
      </div>

      {/* Prominent disclaimer — required by spec */}
      <p className="text-sm text-gray-400 italic">
        All data submitted by users. Traject does not verify individual submissions.
      </p>

      {/* Loading state */}
      {isLoading && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-8 text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-teal-400 mx-auto" />
          <p className="mt-3 text-sm text-gray-400">Loading benchmark data…</p>
        </div>
      )}

      {/* Error state */}
      {!isLoading && error !== null && (
        <div className="bg-gray-800 border border-red-700 rounded-lg p-6">
          <p className="text-sm text-red-400">
            Could not load benchmark data: {error}
          </p>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && error === null && records.length === 0 && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-12 text-center">
          <p className="text-gray-400 text-lg font-medium">
            No benchmark data yet. Be the first to submit!
          </p>
          <p className="mt-3 text-sm text-gray-500">
            Follow the{" "}
            <a
              href="/docs/production-validation.md"
              className="text-teal-400 hover:underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              production validation guide
            </a>{" "}
            to collect and submit your data.
          </p>
        </div>
      )}

      {/* Data table */}
      {!isLoading && error === null && records.length > 0 && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-gray-300">
              <thead>
                <tr className="border-b border-gray-700 text-gray-400">
                  <th className="text-left py-2 px-3">Submitted</th>
                  <th className="text-left py-2 px-3">SDK Version</th>
                  <th className="text-right py-2 px-3">Samples</th>
                  <th className="text-right py-2 px-3">p50 Cost</th>
                  <th className="text-right py-2 px-3">p95 Cost</th>
                  <th className="text-right py-2 px-3">p50 Compression</th>
                  <th className="text-right py-2 px-3">Avg Routing Acc.</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <tr
                    key={r.id}
                    className="border-b border-gray-700/50 hover:bg-gray-700/30"
                  >
                    <td className="py-2 px-3 text-gray-400">
                      {formatDate(r.submitted_at)}
                    </td>
                    <td className="py-2 px-3 font-mono text-teal-400">
                      {r.sdk_version}
                    </td>
                    <td className="py-2 px-3 text-right">
                      {r.sample_count.toLocaleString()}
                    </td>
                    <td className="py-2 px-3 text-right font-mono">
                      ${r.p50_cost_usd}
                    </td>
                    <td className="py-2 px-3 text-right font-mono">
                      ${r.p95_cost_usd}
                    </td>
                    <td className="py-2 px-3 text-right">
                      {formatPct(r.p50_compression_ratio)}
                    </td>
                    <td className="py-2 px-3 text-right">
                      {formatPct(r.avg_routing_accuracy)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
