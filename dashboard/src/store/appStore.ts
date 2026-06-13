/**
 * appStore — global Zustand store for application-level state.
 *
 * Tracks the API key used for backend requests and the active time range
 * filter shared across all dashboard pages.
 */

import { create } from "zustand";
import { TIME_RANGES } from "../lib/constants";

type TimeRange = (typeof TIME_RANGES)[number];

interface AppStore {
  /** Axon API key, defaults to the VITE_AXON_API_KEY environment variable. */
  apiKey: string;
  /** Update the active API key. */
  setApiKey: (key: string) => void;
  /** Active time range filter; defaults to "7d". */
  timeRange: TimeRange;
  /** Update the active time range. */
  setTimeRange: (range: TimeRange) => void;
}

export const useAppStore = create<AppStore>((set) => ({
  apiKey: import.meta.env.VITE_AXON_API_KEY ?? "",
  setApiKey: (key: string) => set({ apiKey: key }),
  timeRange: "7d",
  setTimeRange: (range: TimeRange) => set({ timeRange: range }),
}));
