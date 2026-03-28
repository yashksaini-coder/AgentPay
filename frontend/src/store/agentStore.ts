import { create } from "zustand";
import type { AgentState } from "@/lib/useAgent";
import type { ManagedAgent } from "@/lib/useAgentManager";

interface AgentStore {
  /** Per-port agent state from WebSocket/polling */
  agents: Map<number, AgentState>;
  /** Selected agent port for detail view */
  selectedPort: number | null;
  /** Agent metadata from the manager (label, alive, etc.) */
  managedAgents: ManagedAgent[];
  /** Custom agent names set by the user */
  agentNames: Map<number, string>;

  setAgentState: (port: number, state: AgentState) => void;
  removeAgent: (port: number) => void;
  setSelectedPort: (port: number | null) => void;
  setManagedAgents: (agents: ManagedAgent[]) => void;
  setAgentName: (port: number, name: string) => void;
}

export const useAgentStore = create<AgentStore>((set) => ({
  agents: new Map(),
  selectedPort: null,
  managedAgents: [],
  agentNames: new Map(),

  setAgentState: (port, state) =>
    set((s) => {
      const next = new Map(s.agents);
      next.set(port, state);
      return { agents: next };
    }),

  removeAgent: (port) =>
    set((s) => {
      const next = new Map(s.agents);
      next.delete(port);
      return { agents: next };
    }),

  setSelectedPort: (port) => set({ selectedPort: port }),

  setManagedAgents: (agents) => set({ managedAgents: agents }),

  setAgentName: (port, name) =>
    set((s) => {
      const next = new Map(s.agentNames);
      next.set(port, name);
      return { agentNames: next };
    }),
}));
