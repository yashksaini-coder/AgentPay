"use client";

import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "motion/react";
import { X, CircleDollarSign, CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import ProgressStepper, { type Step } from "./ProgressStepper";
import { createApi, formatWei, type GatedResource, type PricingQuote } from "@/lib/api";

const STEPS: Step[] = [
  { label: "Select" },
  { label: "Review" },
  { label: "Pay" },
  { label: "Receipt" },
];

interface PaymentModalProps {
  resource: GatedResource;
  apiBase: string;
  onClose: () => void;
  /** Optional: peer_id of the provider for trust-adjusted pricing */
  peerId?: string;
}

export default function PaymentModal({ resource, apiBase, onClose, peerId }: PaymentModalProps) {
  const [step, setStep] = useState(0);
  const [quote, setQuote] = useState<PricingQuote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<{ amount: number; resource: string; settled_at: number } | null>(null);

  const api = createApi(apiBase);

  // Step 1 → 2: fetch pricing quote
  const handleReview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const paymentType = resource.payment_type || "oneshot";
      const res = await api.getPricingQuote(paymentType, peerId);
      setQuote(res.quote);
      setStep(1);
    } catch {
      // If pricing service unavailable, use base price
      setQuote({
        service_type: resource.payment_type || "oneshot",
        base_price: resource.price,
        adjusted_price: resource.price,
        trust_discount: 0,
        congestion_premium: 0,
        multiplier: 1,
      });
      setStep(1);
    } finally {
      setLoading(false);
    }
  }, [api, resource, peerId]);

  // Step 2 → 3: authorize payment
  const handlePay = useCallback(async () => {
    setStep(2);
    setLoading(true);
    setError(null);
    try {
      const amount = quote?.adjusted_price ?? resource.price;
      const res = await api.payOneshot(
        resource.path,
        amount,
        peerId || "self",
      );
      setReceipt({ amount: res.amount, resource: res.resource, settled_at: res.settled_at });
      setStep(3);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment failed");
      setStep(1); // go back to review
    } finally {
      setLoading(false);
    }
  }, [api, resource, quote, peerId]);

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-center justify-center"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        {/* Backdrop */}
        <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

        {/* Modal */}
        <motion.div
          className="relative glass-card rounded-2xl p-6 w-[380px] max-w-[90vw] shadow-2xl border border-border-focus"
          initial={{ scale: 0.95, y: 20 }}
          animate={{ scale: 1, y: 0 }}
          exit={{ scale: 0.95, y: 20 }}
        >
          {/* Header */}
          <div className="flex items-center justify-between mb-5">
            <div className="flex items-center gap-2">
              <CircleDollarSign className="w-4 h-4 text-accent" />
              <h2 className="text-sm font-semibold text-text-primary">Payment</h2>
            </div>
            <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Stepper */}
          <div className="mb-6">
            <ProgressStepper steps={STEPS} currentStep={step} />
          </div>

          {/* Error */}
          {error && (
            <div className="mb-4 flex items-start gap-2 p-2.5 rounded-lg bg-danger-subtle border border-danger/20">
              <AlertCircle className="w-3.5 h-3.5 text-danger mt-0.5 shrink-0" />
              <span className="text-[11px] text-danger">{error}</span>
            </div>
          )}

          {/* Step 0: Select resource */}
          {step === 0 && (
            <div className="space-y-4">
              <div className="glass-card rounded-xl p-4">
                <div className="text-[11px] text-text-muted mb-1">Resource</div>
                <code className="text-sm font-mono text-accent">{resource.path}</code>
                <p className="text-[11px] text-text-muted mt-2">{resource.description || "Payment-gated endpoint"}</p>
              </div>
              <div className="flex items-center justify-between px-1">
                <span className="text-[11px] text-text-muted">Price</span>
                <span className="text-sm font-mono font-semibold text-warning">{formatWei(resource.price)}</span>
              </div>
              <Button
                className="w-full h-9 text-xs bg-accent hover:bg-accent-hover text-white font-semibold"
                onClick={handleReview}
                disabled={loading}
              >
                {loading ? "Loading..." : "Review Price"}
              </Button>
            </div>
          )}

          {/* Step 1: Review price */}
          {step === 1 && quote && (
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="flex justify-between text-[11px]">
                  <span className="text-text-muted">Base price</span>
                  <span className="font-mono text-text-primary">{formatWei(quote.base_price)}</span>
                </div>
                {quote.trust_discount > 0 && (
                  <div className="flex justify-between text-[11px]">
                    <span className="text-text-muted">Trust discount</span>
                    <span className="font-mono text-success">-{(quote.trust_discount * 100).toFixed(1)}%</span>
                  </div>
                )}
                {quote.congestion_premium > 0 && (
                  <div className="flex justify-between text-[11px]">
                    <span className="text-text-muted">Congestion premium</span>
                    <span className="font-mono text-warning">+{(quote.congestion_premium * 100).toFixed(1)}%</span>
                  </div>
                )}
                <div className="border-t border-border pt-2 flex justify-between text-xs">
                  <span className="text-text-secondary font-medium">Total</span>
                  <span className="font-mono font-semibold text-accent">{formatWei(quote.adjusted_price)}</span>
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  className="flex-1 h-9 text-xs border-border text-text-muted"
                  onClick={() => setStep(0)}
                >
                  Back
                </Button>
                <Button
                  className="flex-1 h-9 text-xs bg-accent hover:bg-accent-hover text-white font-semibold"
                  onClick={handlePay}
                  disabled={loading}
                >
                  {loading ? "Processing..." : "Authorize Payment"}
                </Button>
              </div>
            </div>
          )}

          {/* Step 2: Processing */}
          {step === 2 && (
            <div className="text-center py-6">
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}
                className="w-8 h-8 mx-auto mb-3 rounded-full border-2 border-accent border-t-transparent"
              />
              <p className="text-xs text-text-secondary">Authorizing payment...</p>
            </div>
          )}

          {/* Step 3: Receipt */}
          {step === 3 && receipt && (
            <div className="space-y-4">
              <div className="text-center py-2">
                <CheckCircle2 className="w-8 h-8 mx-auto mb-2 text-success" />
                <p className="text-sm font-semibold text-text-primary">Payment Complete</p>
              </div>
              <div className="glass-card rounded-xl p-3 space-y-2 text-[11px]">
                <div className="flex justify-between">
                  <span className="text-text-muted">Resource</span>
                  <code className="font-mono text-accent">{receipt.resource}</code>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-muted">Amount</span>
                  <span className="font-mono text-text-primary">{formatWei(receipt.amount)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-muted">Settled</span>
                  <span className="font-mono text-text-muted">
                    {new Date(receipt.settled_at * 1000).toLocaleTimeString()}
                  </span>
                </div>
              </div>
              <Button
                className="w-full h-9 text-xs bg-surface-overlay hover:bg-surface-hover text-text-primary border border-border"
                onClick={onClose}
              >
                Done
              </Button>
            </div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
