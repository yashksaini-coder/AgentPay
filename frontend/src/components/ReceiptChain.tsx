"use client";

import { useState, useEffect, useCallback } from "react";
import type { Api, Receipt } from "@/lib/api";
import { shortenId, formatWei } from "@/lib/api";

interface ReceiptChainProps {
  api: Api;
}

export default function ReceiptChain({ api }: ReceiptChainProps) {
  const [channels, setChannels] = useState<{ channel_id: string; receipt_count: number; chain_valid: boolean }[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await api.getReceipts();
      // Deduplicate channels by channel_id (both sender/receiver may report same channel)
      const seen = new Set<string>();
      const unique = (res.channels || []).filter((ch: { channel_id: string }) => {
        if (seen.has(ch.channel_id)) return false;
        seen.add(ch.channel_id);
        return true;
      });
      setChannels(unique);
    } catch {
      /* ignore */
    }
  }, [api]);

  useEffect(() => { refresh(); }, [refresh]);

  const toggleExpand = async (channelId: string) => {
    if (expanded === channelId) {
      setExpanded(null);
      setReceipts([]);
      return;
    }
    setExpanded(channelId);
    setLoading(true);
    try {
      const res = await api.getChannelReceipts(channelId);
      setReceipts(res.receipts);
    } catch {
      setReceipts([]);
    } finally {
      setLoading(false);
    }
  };

  if (channels.length === 0) {
    return <p className="text-text-muted text-[10px] text-center py-3">No receipts yet</p>;
  }

  return (
    <div className="space-y-1.5">
      {channels.map((ch) => (
        <div key={ch.channel_id} className="bg-surface-overlay rounded-lg border border-border-subtle">
          <button
            onClick={() => toggleExpand(ch.channel_id)}
            className="w-full flex items-center justify-between p-2 text-[10px] hover:bg-surface-hover rounded-lg transition-colors"
          >
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-text-secondary">{shortenId(ch.channel_id, 6)}</span>
              <span className="text-text-muted">{ch.receipt_count} receipts</span>
            </div>
            <span className={`text-[9px] font-medium ${ch.chain_valid ? "text-success" : "text-danger"}`}>
              {ch.chain_valid ? "Valid" : "Broken"}
            </span>
          </button>

          {expanded === ch.channel_id && (
            <div className="border-t border-border-subtle p-2 space-y-1">
              {loading ? (
                <p className="text-text-muted text-[9px] text-center py-1">Loading...</p>
              ) : (
                receipts.map((r, i) => (
                  <div key={r.receipt_id} className="flex items-start gap-1.5">
                    {/* Chain connector */}
                    <div className="flex flex-col items-center pt-1">
                      <div className="w-1.5 h-1.5 rounded-full bg-success/60" />
                      {i < receipts.length - 1 && <div className="w-px h-5 bg-border" />}
                    </div>
                    {/* Receipt info */}
                    <div className="text-[9px] flex-1 min-w-0">
                      <div className="flex justify-between">
                        <span className="text-text-secondary">Nonce {r.nonce}</span>
                        <span className="text-text-muted">{formatWei(r.amount)}</span>
                      </div>
                      <div className="text-text-muted/50 font-mono truncate">{r.receipt_hash.slice(0, 20)}...</div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
