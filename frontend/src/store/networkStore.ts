import { create } from "zustand";
import type { PeerReputation } from "@/lib/api";

export interface NetworkEvent {
  type: string;
  from: string;
  to?: string;
  message: string;
  meta?: string;
  timestamp: number;
}

interface NetworkStore {
  /** Recent network events */
  events: NetworkEvent[];
  /** Payment history for sparkline chart */
  paymentHistory: { t: string; amount: number }[];
  /** Trust scores keyed by peer_id */
  trustScores: Record<string, number>;

  pushEvent: (event: Omit<NetworkEvent, "timestamp">) => void;
  setPaymentHistory: (history: { t: string; amount: number }[]) => void;
  addPaymentDatapoint: (datapoint: { t: string; amount: number }) => void;
  setTrustScores: (scores: Record<string, number>) => void;
}

export const useNetworkStore = create<NetworkStore>((set) => ({
  events: [],
  paymentHistory: [],
  trustScores: {},

  pushEvent: (event) =>
    set((s) => ({
      events: [{ ...event, timestamp: Date.now() }, ...s.events].slice(0, 200),
    })),

  setPaymentHistory: (history) => set({ paymentHistory: history }),

  addPaymentDatapoint: (dp) =>
    set((s) => ({
      paymentHistory: [...s.paymentHistory, dp].slice(-20),
    })),

  setTrustScores: (scores) => set({ trustScores: scores }),
}));
