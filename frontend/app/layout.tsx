import type { Metadata } from "next";
import { Instrument_Serif, Hanken_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";

// Self-hosted via next/font (keine Requests an Google im Browser)
const display = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument",
});
const sans = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-hanken",
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
});

export const metadata: Metadata = {
  title: "KI-Co-Analyst · Multi-Agent Equity Research",
  description: "Multi-Agent-Aktienanalyse · Bachelorthesis Berner Fachhochschule",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de" className={`h-full ${display.variable} ${sans.variable} ${mono.variable}`}>
      <body className="h-full">{children}</body>
    </html>
  );
}
