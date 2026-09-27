"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Menu, X, LogOut } from "lucide-react";
import { Wordmark } from "@/components/brand/Brand";
import { useUsername, logout } from "@/lib/auth";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/analyse",   label: "Analyse" },
  { href: "/history",   label: "Historie" },
  { href: "/settings",  label: "Einstellungen" },
];

/** Kopfzeile der App (ersetzt Topbar + Sidebar): Navigation links,
 *  Ticker-Schnellstart rechts — startet die Analyse direkt auf /analyse. */
export default function AppHeader() {
  const pathname = usePathname();
  const router   = useRouter();
  const [ticker, setTicker]     = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const username = useUsername();

  function start(e: React.FormEvent) {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setTicker("");
    setMenuOpen(false);
    // ts: gleicher Ticker erneut → neue URL, damit /analyse den Start erkennt
    router.push(`/analyse?ticker=${encodeURIComponent(t)}&start=1&ts=${Date.now()}`);
  }

  function handleLogout() {
    logout();
    router.push("/");
  }

  const isActive = (href: string) => pathname === href || pathname.startsWith(href + "/");

  return (
    <header className="bg-card border-b border-line">
      <div className="h-20 px-5 md:px-14 flex items-center justify-between gap-6">
        <div className="flex items-center gap-12">
          <Link href="/dashboard" className="no-underline" aria-label="KI-Co-Analyst Dashboard">
            <Wordmark />
          </Link>
          <nav aria-label="Hauptnavigation" className="hidden lg:flex gap-8 text-[15px] self-stretch">
            {NAV.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                aria-current={isActive(href) ? "page" : undefined}
                className={`flex items-center no-underline border-b-2 pt-0.5 ${
                  isActive(href)
                    ? "text-ink font-semibold border-gold"
                    : "text-muted border-transparent hover:text-ink"
                }`}
              >
                {label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <form onSubmit={start} className="hidden md:flex items-center gap-3">
            <label htmlFor="hdr-ticker" className="label-mono">Ticker</label>
            <input
              id="hdr-ticker"
              value={ticker}
              onChange={e => setTicker(e.target.value)}
              placeholder="z. B. HOLN.SW"
              autoComplete="off"
              className="w-[200px] h-11 px-3.5 border border-line-3 rounded-[2px] bg-white text-[15px] text-ink outline-none focus:border-gold"
            />
            <button type="submit" disabled={!ticker.trim()}
              className="h-11 px-5 rounded-[2px] bg-ink text-cream text-[15px] font-semibold disabled:opacity-50">
              Analyse starten
            </button>
          </form>
          <button type="button" onClick={handleLogout}
            className="hidden lg:flex items-center gap-2 h-11 px-3 text-sm text-muted hover:text-ink"
            title={username ? `Abmelden (${username})` : "Abmelden"}>
            <LogOut size={16} aria-hidden="true" />
            <span className="sr-only">Abmelden</span>
          </button>
          <button type="button" onClick={() => setMenuOpen(v => !v)}
            className="lg:hidden w-11 h-11 flex items-center justify-center text-ink"
            aria-label={menuOpen ? "Menü schliessen" : "Menü öffnen"} aria-expanded={menuOpen}>
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </div>

      {menuOpen && (
        <div className="lg:hidden border-t border-line px-5 py-4 flex flex-col gap-1">
          {NAV.map(({ href, label }) => (
            <Link key={href} href={href} onClick={() => setMenuOpen(false)}
              className={`py-2.5 no-underline text-[15px] ${isActive(href) ? "text-ink font-semibold" : "text-muted"}`}>
              {label}
            </Link>
          ))}
          <form onSubmit={start} className="flex md:hidden gap-2 pt-3">
            <label htmlFor="hdr-ticker-m" className="sr-only">Ticker</label>
            <input id="hdr-ticker-m" value={ticker} onChange={e => setTicker(e.target.value)}
              placeholder="Ticker, z. B. HOLN.SW"
              className="flex-1 h-11 px-3 border border-line-3 rounded-[2px] bg-white text-[15px] outline-none focus:border-gold" />
            <button type="submit" className="h-11 px-4 rounded-[2px] bg-ink text-cream font-semibold">Start</button>
          </form>
          <button type="button" onClick={handleLogout} className="mt-2 py-2.5 text-left text-[15px] text-muted">
            Abmelden{username ? ` (${username})` : ""}
          </button>
        </div>
      )}
    </header>
  );
}
