"use client";

import { useEffect, useState } from "react";
import type { Api, PricingConfig, PricingQuote } from "@/lib/api";

export default function PricingPanel({ api }: { api: Api }) {
  const [config, setConfig] = useState<PricingConfig | null>(null);
  const [quote, setQuote] = useState<PricingQuote | null>(null);
  const [quoteService, setQuoteService] = useState("compute");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await api.getPricingConfig();
        if (!cancelled) setConfig(res.config);
      } catch { /* ignore */ }
      if (!cancelled) setLoading(false);
    };
    load();
    return () => { cancelled = true; };
  }, [api]);

  const fetchQuote = async () => {
    try {
      const res = await api.getPricingQuote(quoteService);
      setQuote(res.quote);
    } catch { /* ignore */ }
  };

  if (loading) return <p className="text-[10px] text-text-muted text-center py-3">Loading pricing...</p>;

  return (
    <div className="space-y-2.5">
      {/* Config display */}
      {config && (
        <div className="space-y-1">
          <h4 className="text-[9px] font-bold uppercase tracking-widest text-text-muted">Engine Config</h4>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px]">
            <span className="text-text-muted">Trust discount</span>
            <span className="font-mono text-text-primary text-right">{(config.trust_discount_factor * 100).toFixed(0)}%</span>
            <span className="text-text-muted">Congestion premium</span>
            <span className="font-mono text-text-primary text-right">{(config.congestion_premium_factor * 100).toFixed(0)}%</span>
            <span className="text-text-muted">Price range</span>
            <span className="font-mono text-text-primary text-right">{config.min_price.toLocaleString()}–{config.max_price.toLocaleString()}</span>
            <span className="text-text-muted">Congestion threshold</span>
            <span className="font-mono text-text-primary text-right">{config.congestion_threshold}</span>
          </div>
        </div>
      )}

      {/* Quote tool */}
      <div className="border-t border-border-subtle pt-2 space-y-1.5">
        <h4 className="text-[9px] font-bold uppercase tracking-widest text-text-muted">Price Quote</h4>
        <div className="flex gap-1.5">
          <select
            value={quoteService}
            onChange={(e) => setQuoteService(e.target.value)}
            className="flex-1 h-6 bg-surface-overlay border border-border rounded-md px-1.5 text-[10px] text-text-primary"
          >
            <option value="compute">Compute</option>
            <option value="storage">Storage</option>
            <option value="inference">Inference</option>
            <option value="relay">Relay</option>
            <option value="data">Data</option>
          </select>
          <button
            onClick={fetchQuote}
            className="h-6 px-2.5 bg-accent/80 hover:bg-accent text-white text-[9px] font-semibold rounded-md transition-colors"
          >
            Quote
          </button>
        </div>

        {quote && (
          <div className="rounded-md bg-accent/5 border border-accent/15 p-2 space-y-0.5">
            <div className="flex items-center justify-between text-[10px]">
              <span className="text-text-muted">Base</span>
              <span className="font-mono text-text-primary">{quote.base_price.toLocaleString()} wei</span>
            </div>
            <div className="flex items-center justify-between text-[10px]">
              <span className="text-text-muted">Adjusted</span>
              <span className="font-mono text-accent font-semibold">{quote.adjusted_price.toLocaleString()} wei</span>
            </div>
            <div className="flex items-center justify-between text-[9px]">
              <span className="text-text-muted">Trust discount</span>
              <span className="font-mono text-success">-{(quote.trust_discount * 100).toFixed(1)}%</span>
            </div>
            <div className="flex items-center justify-between text-[9px]">
              <span className="text-text-muted">Congestion</span>
              <span className="font-mono text-warning">+{(quote.congestion_premium * 100).toFixed(1)}%</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
