"use client";

import { useState, useEffect, useCallback } from "react";
import type { Api, PolicyStats, WalletPolicy } from "@/lib/api";
import { formatWei } from "@/lib/api";

interface PolicyEditorProps {
  api: Api;
}

export default function PolicyEditor({ api }: PolicyEditorProps) {
  const [stats, setStats] = useState<PolicyStats | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<WalletPolicy>({
    max_spend_per_tx: 0,
    max_total_spend: 0,
    rate_limit_per_min: 0,
    peer_whitelist: [],
    peer_blacklist: [],
  });
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await api.getPolicies();
      setStats(res);
      setForm(res.policy);
    } catch {
      /* ignore */
    }
  }, [api]);

  useEffect(() => { refresh(); }, [refresh]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updatePolicies(form);
      await refresh();
      setEditing(false);
    } catch {
      /* ignore */
    } finally {
      setSaving(false);
    }
  };

  if (!stats) {
    return <p className="text-text-muted text-[10px] text-center py-3">Loading policies...</p>;
  }

  return (
    <div className="space-y-2">
      {/* Stats row */}
      <div className="grid grid-cols-2 gap-1.5">
        <div className="bg-surface-overlay rounded-lg p-1.5 text-center border border-border-subtle">
          <div className="text-[9px] text-text-muted">Spent</div>
          <div className="text-[10px] text-text-secondary font-mono">{formatWei(stats.total_spent)}</div>
        </div>
        <div className="bg-surface-overlay rounded-lg p-1.5 text-center border border-border-subtle">
          <div className="text-[9px] text-text-muted">Last Min</div>
          <div className="text-[10px] text-text-secondary font-mono">{stats.payments_last_minute} txns</div>
        </div>
      </div>

      {/* Policy display/edit */}
      {!editing ? (
        <div className="space-y-1">
          <PolicyRow label="Max per tx" value={form.max_spend_per_tx === 0 ? "Unlimited" : formatWei(form.max_spend_per_tx)} />
          <PolicyRow label="Max total" value={form.max_total_spend === 0 ? "Unlimited" : formatWei(form.max_total_spend)} />
          <PolicyRow label="Rate limit" value={form.rate_limit_per_min === 0 ? "Unlimited" : `${form.rate_limit_per_min}/min`} />
          <PolicyRow label="Whitelist" value={form.peer_whitelist.length === 0 ? "Any" : `${form.peer_whitelist.length} peers`} />
          <PolicyRow label="Blacklist" value={form.peer_blacklist.length === 0 ? "None" : `${form.peer_blacklist.length} peers`} />
          <button
            onClick={() => setEditing(true)}
            className="w-full text-[10px] px-2 py-1 bg-surface-overlay hover:bg-surface-hover border border-border rounded-md text-text-secondary mt-1.5 transition-colors"
          >
            Edit Policies
          </button>
        </div>
      ) : (
        <div className="space-y-1.5">
          <PolicyInput label="Max per tx (wei, 0=unlimited)" value={form.max_spend_per_tx}
            onChange={(v) => setForm({ ...form, max_spend_per_tx: v })} />
          <PolicyInput label="Max total (wei, 0=unlimited)" value={form.max_total_spend}
            onChange={(v) => setForm({ ...form, max_total_spend: v })} />
          <PolicyInput label="Rate limit (/min, 0=unlimited)" value={form.rate_limit_per_min}
            onChange={(v) => setForm({ ...form, rate_limit_per_min: v })} />
          <div className="flex gap-1.5">
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex-1 text-[10px] px-2 py-1 bg-success/10 hover:bg-success/20 border border-success/20 rounded-md text-success disabled:opacity-40 transition-colors"
            >
              {saving ? "Saving..." : "Save"}
            </button>
            <button
              onClick={() => { setEditing(false); if (stats) setForm(stats.policy); }}
              className="flex-1 text-[10px] px-2 py-1 bg-surface-overlay hover:bg-surface-hover border border-border rounded-md text-text-secondary transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PolicyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-[10px]">
      <span className="text-text-muted">{label}</span>
      <span className="text-text-secondary font-mono">{value}</span>
    </div>
  );
}

function PolicyInput({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="text-[9px] text-text-muted block mb-0.5">{label}</label>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value) || 0)}
        className="w-full h-6 bg-surface-overlay border border-border rounded-md px-2 text-[10px] font-mono text-text-primary focus-ring"
      />
    </div>
  );
}
