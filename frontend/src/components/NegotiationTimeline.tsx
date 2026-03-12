"use client";

import { useState, useEffect, useCallback } from "react";
import type { Api, Negotiation } from "@/lib/api";
import { shortenId, formatWei } from "@/lib/api";

interface NegotiationTimelineProps {
  api: Api;
}

const STATE_COLORS: Record<string, string> = {
  proposed: "text-accent",
  countered: "text-warning",
  accepted: "text-success",
  rejected: "text-danger",
  expired: "text-text-muted",
  channel_opened: "text-success",
};

const STEP_ORDER = ["proposed", "countered", "accepted", "channel_opened"];

export default function NegotiationTimeline({ api }: NegotiationTimelineProps) {
  const [negotiations, setNegotiations] = useState<Negotiation[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [counterPrices, setCounterPrices] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getNegotiations();
      setNegotiations(res.negotiations);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => { refresh(); }, [refresh]);

  const handleAccept = async (id: string) => {
    setActionLoading(id);
    try {
      await api.acceptNegotiation(id);
      await refresh();
    } catch { /* ignore */ }
    finally { setActionLoading(null); }
  };

  const handleReject = async (id: string) => {
    setActionLoading(id);
    try {
      await api.rejectNegotiation(id);
      await refresh();
    } catch { /* ignore */ }
    finally { setActionLoading(null); }
  };

  const handleCounter = async (id: string) => {
    const price = parseInt(counterPrices[id]);
    if (!price || price <= 0) return;
    setActionLoading(id);
    try {
      await api.counterNegotiation(id, price);
      setCounterPrices((prev) => { const next = { ...prev }; delete next[id]; return next; });
      await refresh();
    } catch { /* ignore */ }
    finally { setActionLoading(null); }
  };

  if (negotiations.length === 0) {
    return <p className="text-text-muted text-[10px] text-center py-3">No negotiations yet</p>;
  }

  return (
    <div className="space-y-1.5">
      {negotiations.map((neg) => {
        const currentIdx = STEP_ORDER.indexOf(neg.state);
        const isActive = neg.state === "proposed" || neg.state === "countered";
        const isBusy = actionLoading === neg.negotiation_id;
        return (
          <div key={neg.negotiation_id} className="bg-surface-overlay rounded-lg p-2 border border-border-subtle">
            {/* Header */}
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[9px] font-mono text-text-muted">{shortenId(neg.negotiation_id, 6)}</span>
              <span className={`text-[9px] font-semibold uppercase ${STATE_COLORS[neg.state] || "text-text-muted"}`}>
                {neg.state}
              </span>
            </div>

            {/* Step indicator */}
            <div className="flex items-center gap-0.5 mb-1.5">
              {STEP_ORDER.map((step, i) => {
                const stepActive = i <= currentIdx && currentIdx >= 0;
                const isRejected = neg.state === "rejected" || neg.state === "expired";
                return (
                  <div key={step} className="flex items-center gap-0.5 flex-1">
                    <div className={`w-1.5 h-1.5 rounded-full ${
                      isRejected && i === currentIdx ? "bg-danger" :
                      stepActive ? "bg-success" : "bg-border-focus"
                    }`} />
                    {i < STEP_ORDER.length - 1 && (
                      <div className={`flex-1 h-px ${stepActive && i < currentIdx ? "bg-success/50" : "bg-border"}`} />
                    )}
                  </div>
                );
              })}
            </div>

            {/* Details */}
            <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[9px]">
              <span className="text-text-muted">Service</span>
              <span className="text-text-secondary">{neg.service_type}</span>
              <span className="text-text-muted">Price</span>
              <span className="text-text-secondary">{formatWei(neg.current_price)}/call</span>
              <span className="text-text-muted">Deposit</span>
              <span className="text-text-secondary">{formatWei(neg.channel_deposit)}</span>
              <span className="text-text-muted">Initiator</span>
              <span className="text-text-secondary font-mono">{shortenId(neg.initiator, 4)}</span>
              <span className="text-text-muted">Responder</span>
              <span className="text-text-secondary font-mono">{shortenId(neg.responder, 4)}</span>
            </div>

            {/* Action buttons for active negotiations */}
            {isActive && (
              <div className="mt-2 pt-1.5 border-t border-border-subtle space-y-1.5">
                <div className="flex gap-1">
                  <button
                    onClick={() => handleAccept(neg.negotiation_id)}
                    disabled={isBusy}
                    className="flex-1 h-6 text-[9px] font-medium bg-success/10 hover:bg-success/20 border border-success/20 rounded-md text-success disabled:opacity-40 transition-colors"
                  >
                    {isBusy ? "..." : "Accept"}
                  </button>
                  <button
                    onClick={() => handleReject(neg.negotiation_id)}
                    disabled={isBusy}
                    className="flex-1 h-6 text-[9px] font-medium bg-danger/10 hover:bg-danger/20 border border-danger/20 rounded-md text-danger disabled:opacity-40 transition-colors"
                  >
                    {isBusy ? "..." : "Reject"}
                  </button>
                </div>
                <div className="flex gap-1">
                  <input
                    type="number"
                    placeholder="Counter price..."
                    value={counterPrices[neg.negotiation_id] ?? ""}
                    onChange={(e) => setCounterPrices((prev) => ({ ...prev, [neg.negotiation_id]: e.target.value }))}
                    className="flex-1 h-6 bg-surface-raised border border-border rounded-md px-2 text-[9px] font-mono text-text-primary placeholder:text-text-muted/50 focus-ring"
                  />
                  <button
                    onClick={() => handleCounter(neg.negotiation_id)}
                    disabled={isBusy || !counterPrices[neg.negotiation_id]}
                    className="h-6 px-2 text-[9px] font-medium bg-warning/10 hover:bg-warning/20 border border-warning/20 rounded-md text-warning disabled:opacity-40 transition-colors"
                  >
                    Counter
                  </button>
                </div>
              </div>
            )}

            {/* History */}
            {neg.history.length > 0 && (
              <div className={`${isActive ? "mt-1.5" : "mt-2"} pt-1.5 border-t border-border-subtle`}>
                {neg.history.map((evt, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-[9px] py-0.5">
                    <span className={`uppercase font-semibold ${STATE_COLORS[evt.action] || "text-text-muted"}`}>
                      {evt.action}
                    </span>
                    <span className="text-text-muted">{formatWei(evt.price)}</span>
                    <span className="text-text-muted/60 ml-auto font-mono">{shortenId(evt.by, 4)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
