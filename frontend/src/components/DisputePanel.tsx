"use client";

import { useEffect, useState } from "react";
import type { Api, Dispute } from "@/lib/api";

const RESOLUTION_COLORS: Record<string, string> = {
  PENDING: "text-warning bg-warning/10 border-warning/20",
  CHALLENGER_WINS: "text-success bg-success/10 border-success/20",
  RESPONDER_WINS: "text-accent bg-accent/10 border-accent/20",
  SETTLED: "text-text-muted bg-surface-overlay border-border",
};

export default function DisputePanel({ api }: { api: Api }) {
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await api.getDisputes();
        if (!cancelled) setDisputes(res.disputes ?? []);
      } catch { /* ignore */ }
      if (!cancelled) setLoading(false);
    };
    load();
    const interval = setInterval(load, 6000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [api]);

  const handleScan = async () => {
    setScanning(true);
    try {
      const res = await api.scanDisputes();
      if (res.disputes_filed > 0) {
        const updated = await api.getDisputes();
        setDisputes(updated.disputes ?? []);
      }
    } catch { /* ignore */ }
    setScanning(false);
  };

  if (loading) return <p className="text-[10px] text-text-muted text-center py-3">Loading disputes...</p>;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[9px] font-mono text-text-muted">{disputes.length} dispute{disputes.length !== 1 ? "s" : ""}</span>
        <button
          onClick={handleScan}
          disabled={scanning}
          className="text-[9px] font-medium text-accent hover:text-accent/80 disabled:opacity-50 transition-colors"
        >
          {scanning ? "Scanning..." : "Scan"}
        </button>
      </div>

      {disputes.length === 0 ? (
        <div className="text-center py-3">
          <div className="w-6 h-6 rounded-full bg-success/10 flex items-center justify-center mx-auto mb-1.5">
            <span className="text-success text-[10px]">&#10003;</span>
          </div>
          <p className="text-[10px] text-text-muted">No disputes</p>
        </div>
      ) : (
        disputes.slice(0, 8).map((d) => {
          const style = RESOLUTION_COLORS[d.resolution] ?? RESOLUTION_COLORS.PENDING;
          return (
            <div key={d.dispute_id} className="rounded-md bg-surface-overlay/40 border border-border-subtle p-2 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-semibold text-text-primary">{d.reason}</span>
                <span className={`text-[8px] font-bold uppercase px-1.5 py-0.5 rounded border ${style}`}>
                  {d.resolution}
                </span>
              </div>
              <div className="text-[9px] text-text-muted font-mono">
                ch: {d.channel_id.slice(0, 12)}...
              </div>
              {d.slash_amount > 0 && (
                <div className="text-[9px] text-danger">
                  Slash: {d.slash_amount.toLocaleString()} wei
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
