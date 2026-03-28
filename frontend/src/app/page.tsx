"use client";

import Link from "next/link";
import { ArrowRight, Zap, Shield, Globe, Layers, FileCheck, Network, CircleDollarSign, Lock, Cpu, GitBranch, BarChart3 } from "lucide-react";
import { BlurFade } from "@/components/ui/blur-fade";
import { ShimmerButton } from "@/components/ui/shimmer-button";
import { AnimatedGradientText } from "@/components/ui/animated-gradient-text";
import { BorderBeam } from "@/components/ui/border-beam";
import { Particles } from "@/components/ui/particles";
import { OrbitingCircles } from "@/components/ui/orbiting-circles";

const FEATURES = [
  {
    icon: Network,
    title: "P2P Discovery",
    desc: "Agents find each other via mDNS and libp2p. No centralized registry.",
    gradient: "from-violet-500/20 to-violet-500/0",
  },
  {
    icon: CircleDollarSign,
    title: "Payment Channels",
    desc: "Off-chain cumulative vouchers. Sub-millisecond micropayments, zero gas.",
    gradient: "from-emerald-500/20 to-emerald-500/0",
  },
  {
    icon: Lock,
    title: "x402 Gateway",
    desc: "Payment-gated endpoints following the x402 spec. Pay to access services.",
    gradient: "from-amber-500/20 to-amber-500/0",
  },
  {
    icon: Layers,
    title: "Multi-Chain Settlement",
    desc: "Settle on Ethereum, Algorand, or Filecoin FEVM — selectable at runtime.",
    gradient: "from-purple-500/20 to-purple-500/0",
  },
  {
    icon: Shield,
    title: "Trust Scoring",
    desc: "Dynamic reputation from payment history. Reliable peers earn discounts.",
    gradient: "from-cyan-500/20 to-cyan-500/0",
  },
  {
    icon: FileCheck,
    title: "SLA Enforcement",
    desc: "Negotiated terms, latency monitoring, dispute resolution, receipt chains.",
    gradient: "from-orange-500/20 to-orange-500/0",
  },
];


export default function LandingPage() {
  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Background particles */}
      <Particles
        className="fixed inset-0 z-0"
        quantity={60}
        color="#7c6df0"
        size={0.4}
        staticity={40}
        ease={60}
      />

      {/* ── Hero ── */}
      <section className="relative z-10 pt-24 pb-16 sm:pt-32 sm:pb-24 px-4">
        <div className="max-w-4xl mx-auto text-center">
          {/* Badge */}
          <BlurFade delay={0} direction="down">
            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full border border-white/[0.06] bg-white/[0.02] mb-8">
              <Zap className="w-3 h-3 text-amber-400" />
              <span className="text-[11px] font-medium text-text-secondary tracking-wide">
                Built for Filecoin Agents + ARIA Scaling Trust
              </span>
            </div>
          </BlurFade>

          {/* Heading */}
          <BlurFade delay={0.1} direction="down">
            <h1 className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-bold tracking-[-0.03em] leading-[1.05] mb-6">
              <span className="text-text-primary">Decentralized</span>
              <br />
              <AnimatedGradientText
                colorFrom="#7c6df0"
                colorTo="#c084fc"
                speed={1.5}
                className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-bold tracking-[-0.03em]"
              >
                Micropayments
              </AnimatedGradientText>
              <br />
              <span className="text-text-muted">for AI Agents</span>
            </h1>
          </BlurFade>

          {/* Subtitle */}
          <BlurFade delay={0.2} direction="down">
            <p className="text-base sm:text-lg text-text-secondary/80 max-w-xl mx-auto mb-10 leading-relaxed font-light">
              Agents discover peers via libp2p, negotiate terms, exchange
              signed vouchers off-chain, and settle on any EVM chain.
            </p>
          </BlurFade>

          {/* CTAs */}
          <BlurFade delay={0.3} direction="down">
            <div className="flex items-center justify-center gap-3">
              <Link href="/dashboard">
                <ShimmerButton
                  shimmerColor="#a78bfa"
                  shimmerSize="0.08em"
                  background="rgba(124, 109, 240, 0.9)"
                  borderRadius="12px"
                  className="h-11 px-7 text-sm font-semibold"
                >
                  Launch Dashboard
                  <ArrowRight className="w-4 h-4 ml-2" />
                </ShimmerButton>
              </Link>
              <Link href="/marketplace">
                <button className="h-11 px-7 rounded-xl text-sm font-medium text-text-secondary border border-white/[0.08] bg-white/[0.02] hover:bg-white/[0.05] hover:text-text-primary transition-all duration-200">
                  Browse Services
                </button>
              </Link>
            </div>
          </BlurFade>

          {/* Hero Visualization — Orbiting agents */}
          <BlurFade delay={0.5} direction="up">
            <div className="relative mt-16 mx-auto w-[340px] h-[340px] flex items-center justify-center">
              {/* Center node */}
              <div className="w-14 h-14 rounded-2xl bg-accent/15 border border-accent/20 flex items-center justify-center backdrop-blur-sm z-10">
                <CircleDollarSign className="w-6 h-6 text-accent" />
              </div>

              {/* Inner orbit — protocol icons */}
              <OrbitingCircles radius={80} duration={25} iconSize={36} path={false}>
                <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                  <GitBranch className="w-4 h-4 text-emerald-400" />
                </div>
                <div className="w-9 h-9 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
                  <Lock className="w-4 h-4 text-amber-400" />
                </div>
                <div className="w-9 h-9 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center">
                  <Shield className="w-4 h-4 text-cyan-400" />
                </div>
              </OrbitingCircles>

              {/* Outer orbit — agent nodes */}
              <OrbitingCircles radius={150} duration={35} reverse iconSize={40} path={false}>
                <div className="w-10 h-10 rounded-xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
                  <Cpu className="w-4.5 h-4.5 text-violet-400" />
                </div>
                <div className="w-10 h-10 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center">
                  <BarChart3 className="w-4.5 h-4.5 text-rose-400" />
                </div>
                <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
                  <Globe className="w-4.5 h-4.5 text-blue-400" />
                </div>
                <div className="w-10 h-10 rounded-xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center">
                  <Network className="w-4.5 h-4.5 text-teal-400" />
                </div>
              </OrbitingCircles>

              {/* Orbit path rings */}
              <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 340 340">
                <circle cx="170" cy="170" r="80" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
                <circle cx="170" cy="170" r="150" fill="none" stroke="rgba(255,255,255,0.03)" strokeWidth="1" strokeDasharray="4 4" />
              </svg>
            </div>
          </BlurFade>
        </div>
      </section>

      {/* ── Features ── */}
      <section className="relative z-10 py-24 px-4">
        <div className="max-w-5xl mx-auto">
          <BlurFade delay={0} inView>
            <div className="text-center mb-16">
              <p className="text-[11px] font-semibold tracking-[0.2em] uppercase text-accent mb-3">
                Protocol
              </p>
              <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
                How It Works
              </h2>
              <p className="text-sm text-text-muted mt-3 max-w-md mx-auto leading-relaxed">
                Complete payment infrastructure for autonomous agents — discovery to settlement.
              </p>
            </div>
          </BlurFade>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {FEATURES.map((feat, i) => (
              <BlurFade key={feat.title} delay={0.05 * i} inView>
                <div className="group relative rounded-2xl border border-white/[0.06] bg-white/[0.015] p-6 transition-all duration-300 hover:border-white/[0.12] hover:bg-white/[0.025] overflow-hidden">
                  {/* Gradient background on hover */}
                  <div className={`absolute inset-0 bg-gradient-to-br ${feat.gradient} opacity-0 group-hover:opacity-100 transition-opacity duration-500`} />

                  <div className="relative z-10">
                    <div className="w-10 h-10 rounded-xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-4 group-hover:border-white/[0.12] transition-colors">
                      <feat.icon className="w-5 h-5 text-text-secondary group-hover:text-text-primary transition-colors" />
                    </div>
                    <h3 className="text-sm font-semibold text-text-primary mb-2 tracking-tight">
                      {feat.title}
                    </h3>
                    <p className="text-[13px] text-text-muted leading-relaxed">
                      {feat.desc}
                    </p>
                  </div>

                  {/* Border beam on hover */}
                  <BorderBeam
                    size={200}
                    duration={8}
                    colorFrom="#7c6df0"
                    colorTo="#c084fc"
                    className="opacity-0 group-hover:opacity-100 transition-opacity duration-500"
                  />
                </div>
              </BlurFade>
            ))}
          </div>
        </div>
      </section>

    </div>
  );
}
