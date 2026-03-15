"use client";

import { useState, useEffect, useCallback } from "react";
import type { Api, ERC8004Identity } from "@/lib/api";
import { shortenAddr } from "@/lib/api";

interface IdentityPanelProps {
  api: Api;
}

export default function IdentityPanel({ api }: IdentityPanelProps) {
  const [identity, setIdentity] = useState<ERC8004Identity | null>(null);
  const [loading, setLoading] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getERC8004Status();
      setIdentity(res);
      setError("");
    } catch {
      setIdentity(null);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleRegister = async () => {
    setRegistering(true);
    setError("");
    try {
      const res = await api.registerERC8004();
      setIdentity(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Registration failed");
    } finally {
      setRegistering(false);
    }
  };

  if (!identity || !identity.enabled) {
    return (
      <div className="space-y-1.5">
        <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
          On-Chain Identity
        </h3>
        <div className="text-xs text-zinc-500">
          ERC-8004 not configured
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
        On-Chain Identity (ERC-8004)
      </h3>

      <div className="bg-zinc-800/50 rounded-lg p-2.5 space-y-1.5 text-xs">
        {/* Registration Status */}
        <div className="flex items-center justify-between">
          <span className="text-zinc-400">Status</span>
          {identity.registered_on_chain ? (
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              <span className="text-emerald-400 font-medium">Registered</span>
            </span>
          ) : (
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              <span className="text-amber-400 font-medium">Not Registered</span>
            </span>
          )}
        </div>

        {/* Agent ID */}
        {identity.agent_id !== null && (
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Agent ID</span>
            <span className="font-mono text-zinc-200">#{identity.agent_id}</span>
          </div>
        )}

        {/* ETH Address */}
        {identity.eth_address && (
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Address</span>
            <span className="font-mono text-zinc-300">
              {shortenAddr(identity.eth_address)}
            </span>
          </div>
        )}

        {/* Chain ID */}
        {identity.chain_id > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Chain</span>
            <span className="text-zinc-300">
              {identity.chain_id === 1 ? "Mainnet" :
               identity.chain_id === 31337 ? "Anvil" :
               identity.chain_id === 314159 ? "Filecoin Calibration" :
               `Chain ${identity.chain_id}`}
            </span>
          </div>
        )}

        {/* Registration TX */}
        {identity.registration_tx && (
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Tx</span>
            <span className="font-mono text-zinc-400 text-[10px]">
              {identity.registration_tx.slice(0, 10)}...
            </span>
          </div>
        )}

        {/* Register Button */}
        {!identity.registered_on_chain && (
          <button
            onClick={handleRegister}
            disabled={registering}
            className="w-full mt-1.5 px-2 py-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-600 text-white text-xs rounded transition-colors"
          >
            {registering ? "Registering..." : "Register On-Chain"}
          </button>
        )}

        {error && (
          <div className="text-red-400 text-[10px] mt-1">{error}</div>
        )}
      </div>

      {loading && (
        <div className="text-[10px] text-zinc-500">Refreshing...</div>
      )}
    </div>
  );
}
