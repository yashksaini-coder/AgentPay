"use client";

import { motion } from "framer-motion";
import { Check } from "lucide-react";

export interface Step {
  label: string;
  description?: string;
}

interface ProgressStepperProps {
  steps: Step[];
  currentStep: number; // 0-indexed
}

export default function ProgressStepper({ steps, currentStep }: ProgressStepperProps) {
  return (
    <div className="flex items-center gap-1 w-full">
      {steps.map((step, i) => {
        const done = i < currentStep;
        const active = i === currentStep;

        return (
          <div key={step.label} className="flex items-center flex-1 last:flex-none">
            {/* Step circle + label */}
            <div className="flex flex-col items-center gap-1 min-w-[28px]">
              <motion.div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-semibold border transition-colors ${
                  done
                    ? "bg-success/20 border-success/40 text-success"
                    : active
                      ? "bg-accent/20 border-accent/40 text-accent"
                      : "bg-surface-overlay border-border text-text-muted"
                }`}
                animate={active ? { scale: [1, 1.08, 1] } : {}}
                transition={{ duration: 1.5, repeat: Infinity }}
              >
                {done ? <Check className="w-3.5 h-3.5" /> : i + 1}
              </motion.div>
              <span className={`text-[9px] text-center leading-tight ${active ? "text-text-primary" : "text-text-muted"}`}>
                {step.label}
              </span>
            </div>

            {/* Connector line */}
            {i < steps.length - 1 && (
              <div className="flex-1 h-px mx-1.5 relative">
                <div className="absolute inset-0 bg-border" />
                {done && (
                  <motion.div
                    className="absolute inset-0 bg-success/40"
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: 1 }}
                    transition={{ duration: 0.3 }}
                    style={{ transformOrigin: "left" }}
                  />
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
