import type { Metadata } from "next";
import "./globals.css";
import ClientShell from "@/components/ClientShell";

export const metadata: Metadata = {
  title: "AgentPay — P2P Micropayments for AI Agents",
  description:
    "Decentralized payment channels for autonomous AI agents over libp2p + Ethereum",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <ClientShell>{children}</ClientShell>
      </body>
    </html>
  );
}
