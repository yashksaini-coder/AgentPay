"use client";

import { useEffect, useState } from "react";
import type { Api, SLAViolation } from "@/lib/api";

export default function SLAPanel({ api }: { api: Api }) {
  const [violations, setViolations] = useState<SLAViolation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await api.getSLAViolations();
        if (!cancelled) setViolations(res.violations ?? []);
      } catch { /* ignore */ }
      if (!cancelled) setLoading(false);
    };
    load();
    const interval = setInterval(load, 6000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [api]);

  if (loading) return <p className="text-[10px] text-text-muted text-center py-3">Loading SLA data...</p>;

  if (violations.length === 0) {
    return (
      <div className="text-center py-3">
        <div className="w-6 h-6 rounded-full bg-success/10 flex items-center justify-center mx-auto mb-1.5">
          <span className="text-success text-[10px]">&#10003;</span>
        </div>
        <p className="text-[10px] text-text-muted">All channels SLA-compliant</p>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[9px] font-mono text-danger">{violations.length} violation{violations.length !== 1 ? "s" : ""}</span>
      </div>
      {violations.slice(0, 10).map((v, i) => (
        <div key={i} className="rounded-md bg-danger/5 border border-danger/15 p-2 space-y-0.5">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-semibold text-danger">{v.violation_type}</span>
            <span className="text-[8px] font-mono text-text-muted">
              {v.channel_id.slice(0, 10)}...
            </span>
          </div>
          <div className="flex items-center gap-2 text-[9px] text-text-muted">
            <span>measured: <span className="font-mono text-text-primary">{v.measured_value.toFixed(2)}</span></span>
            <span>threshold: <span className="font-mono text-danger">{v.threshold_value.toFixed(2)}</span></span>
          </div>
        </div>
      ))}
    </div>
  );
}
