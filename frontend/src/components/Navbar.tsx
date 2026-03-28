"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Store, LayoutDashboard, Wifi, WifiOff, Loader2 } from "lucide-react";
import { useBackendStatus, type BackendStatus } from "@/lib/useBackendStatus";

const NAV_ITEMS = [
  { href: "/", label: "Home", icon: Activity },
  { href: "/marketplace", label: "Marketplace", icon: Store },
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
];

const STATUS_CONFIG: Record<BackendStatus, { dot: string; text: string; icon: typeof Wifi }> = {
  connecting: { dot: "bg-amber-400 animate-pulse", text: "Connecting...", icon: Loader2 },
  online:     { dot: "bg-emerald-400", text: "Online", icon: Wifi },
  offline:    { dot: "bg-red-400", text: "Offline", icon: WifiOff },
};

export default function Navbar() {
  const pathname = usePathname();
  const { status, agentCount } = useBackendStatus();
  const cfg = STATUS_CONFIG[status];
  const StatusIcon = cfg.icon;

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 border-b border-white/[0.04] bg-[#06060b]/70 backdrop-blur-2xl backdrop-saturate-150">
      <div className="max-w-screen-2xl mx-auto flex items-center justify-between h-14 px-5">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5 group">
          <div className="w-7 h-7 rounded-lg bg-accent/12 border border-accent/20 flex items-center justify-center group-hover:bg-accent/18 transition-colors">
            <Activity className="w-3.5 h-3.5 text-accent" />
          </div>
          <span className="text-[15px] font-semibold text-text-primary tracking-[-0.02em]">
            Agent<span className="text-accent">Pay</span>
          </span>
        </Link>

        {/* Navigation */}
        <div className="flex items-center gap-0.5 p-1 rounded-xl bg-white/[0.02] border border-white/[0.04]">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || (href !== "/" && pathname.startsWith(href));
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-[13px] font-medium transition-all duration-200 ${
                  active
                    ? "bg-accent/12 text-accent shadow-sm shadow-accent/5"
                    : "text-text-muted hover:text-text-secondary hover:bg-white/[0.04]"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {label}
              </Link>
            );
          })}
        </div>

        {/* Backend status */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/[0.02] border border-white/[0.04]">
          <StatusIcon className={`w-3 h-3 ${status === "connecting" ? "animate-spin text-amber-400" : status === "online" ? "text-emerald-400" : "text-red-400"}`} />
          <div className="flex items-center gap-1.5">
            <div className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
            <span className={`text-[11px] font-medium ${status === "online" ? "text-emerald-400" : status === "offline" ? "text-red-400" : "text-amber-400"}`}>
              {cfg.text}
            </span>
          </div>
          {status === "online" && agentCount > 0 && (
            <span className="text-[10px] font-mono text-text-muted">
              {agentCount} node{agentCount !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </div>
    </nav>
  );
}
