import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "KI-Co-Analyst · Research Platform",
  description: "KI-gestützte Equity-Research-Plattform · BFH Bachelor Thesis",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de" className="h-full">
      <body className="h-full">{children}</body>
    </html>
  );
}
