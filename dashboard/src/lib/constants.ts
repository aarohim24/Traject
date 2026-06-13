/**
 * constants — shared application-wide constants.
 *
 * Centralises time range options, color palette tokens, pagination defaults,
 * and polling intervals so they are changed in exactly one place.
 */

/** Available time range options for all date-scoped queries. */
export const TIME_RANGES = ["24h", "7d", "30d"] as const;

/** Tailwind class tokens and Recharts hex values for the dark dashboard theme. */
export const COLORS = {
  bgPrimary: "bg-gray-950",
  bgSecondary: "bg-gray-900",
  bgCard: "bg-gray-800",
  border: "border-gray-700",
  textPrimary: "text-gray-100",
  textMuted: "text-gray-400",
  accent: "text-teal-400",
  accentBg: "bg-teal-500",
  success: "text-green-400",
  warning: "text-yellow-400",
  error: "text-red-400",
  /** Teal-400 hex value for use in Recharts components that accept raw CSS colours. */
  chartPrimary: "#2dd4bf",
} as const;

/** Default number of rows per page in paginated tables (e.g. SpanExplorer). */
export const DEFAULT_PAGE_SIZE = 50;

/** TanStack Query refetch interval in milliseconds (60 seconds). */
export const REFETCH_INTERVAL_MS = 60_000;
