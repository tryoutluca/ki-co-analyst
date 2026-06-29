"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { login as apiLogin, register as apiRegister } from "@/lib/api";

type ModalType = "none" | "login" | "register";

/* ─── Shared input style ─────────────────────────────────────────────── */
const INPUT = "w-full px-4 py-3 rounded-lg border text-sm outline-none transition-all border-slate-200 focus:border-amber-400 focus:ring-2 focus:ring-amber-100 bg-slate-50 text-slate-800 placeholder-slate-400";
const LABEL = "block text-xs font-semibold tracking-widest uppercase mb-1.5 text-slate-400";
const GOLD_BAR = "h-1 w-full";

/* ─── Spinner ────────────────────────────────────────────────────────── */
function Spinner() {
  return (
    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
    </svg>
  );
}

/* ─── Login form ─────────────────────────────────────────────────────── */
function LoginForm({
  onClose,
  onSwitch,
  onSuccess,
}: {
  onClose: () => void;
  onSwitch: () => void;
  onSuccess: () => void;
}) {
  const [user, setUser] = useState("");
  const [pw, setPw]     = useState("");
  const [err, setErr]   = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await apiLogin(user.trim(), pw);
      onSuccess();
    } catch {
      setErr("Ungültige Anmeldedaten.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-2xl overflow-hidden w-full max-w-md">
      <div className={GOLD_BAR} style={{ background: "linear-gradient(90deg,#c9a84c,#e8c96a)" }} />
      <div className="p-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="font-serif text-2xl font-bold text-slate-800">Anmelden</h2>
            <p className="text-xs text-slate-400 mt-0.5">Willkommen zurück</p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-300 hover:text-slate-600 text-2xl leading-none transition-colors">×</button>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className={LABEL}>Benutzername</label>
            <input type="text" value={user} onChange={e => setUser(e.target.value)}
              placeholder="admin" autoComplete="username" required className={INPUT} />
          </div>
          <div>
            <label className={LABEL}>Passwort</label>
            <input type="password" value={pw} onChange={e => setPw(e.target.value)}
              placeholder="••••••••" autoComplete="current-password" required className={INPUT} />
          </div>
          {err && <div className="px-4 py-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">{err}</div>}
          <button type="submit" disabled={busy}
            className="w-full py-3.5 rounded-lg font-semibold text-sm text-white transition-all disabled:opacity-60 shadow-lg"
            style={{ background: busy ? "#8a9bb0" : "#0a1628" }}>
            {busy ? <span className="flex items-center justify-center gap-2"><Spinner /> Anmelden…</span> : "Anmelden →"}
          </button>
        </form>

        <div className="mt-5 pt-5 border-t border-slate-100 flex flex-col items-center gap-2">
          <p className="text-xs text-slate-400">
            Noch kein Konto?{" "}
            <button type="button" onClick={onSwitch} className="font-semibold underline" style={{ color: "#c9a84c" }}>Registrieren</button>
          </p>
          <p className="text-xs text-slate-400">Demo: <strong>admin</strong> / <strong>analyst2025</strong></p>
        </div>
      </div>
    </div>
  );
}

/* ─── Register form ──────────────────────────────────────────────────── */
function RegisterForm({
  onClose,
  onSwitch,
}: {
  onClose: () => void;
  onSwitch: () => void;
}) {
  const [email, setEmail] = useState("");
  const [user, setUser]   = useState("");
  const [pw, setPw]       = useState("");
  const [pw2, setPw2]     = useState("");
  const [err, setErr]     = useState("");
  const [ok, setOk]       = useState(false);
  const [busy, setBusy]   = useState(false);

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setErr("");
    if (pw !== pw2) { setErr("Passwörter stimmen nicht überein."); return; }
    if (pw.length < 8) { setErr("Passwort muss mindestens 8 Zeichen haben."); return; }
    setBusy(true);
    try {
      await apiRegister(email.trim(), user.trim(), pw);
      setOk(true);
    } catch (ex: unknown) {
      const detail = (ex as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setErr(detail ?? "Registrierung fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  if (ok) {
    return (
      <div className="bg-white rounded-2xl shadow-2xl overflow-hidden w-full max-w-md">
        <div className={GOLD_BAR} style={{ background: "linear-gradient(90deg,#c9a84c,#e8c96a)" }} />
        <div className="p-8 text-center">
          <button type="button" onClick={onClose} className="absolute top-4 right-4 text-slate-300 hover:text-slate-600 text-2xl leading-none">×</button>
          <div className="text-5xl mb-4">✅</div>
          <h2 className="font-serif text-2xl font-bold text-slate-800 mb-2">Registrierung erfolgreich!</h2>
          <p className="text-sm text-slate-500 mb-6">Du kannst dich jetzt anmelden.</p>
          <button type="button" onClick={onSwitch}
            className="px-6 py-3 rounded-lg font-semibold text-sm text-white"
            style={{ background: "#0a1628" }}>
            Jetzt anmelden →
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl shadow-2xl overflow-hidden w-full max-w-md">
      <div className={GOLD_BAR} style={{ background: "linear-gradient(90deg,#c9a84c,#e8c96a)" }} />
      <div className="p-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="font-serif text-2xl font-bold text-slate-800">Registrieren</h2>
            <p className="text-xs text-slate-400 mt-0.5">Kostenloses Konto erstellen</p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-300 hover:text-slate-600 text-2xl leading-none transition-colors">×</button>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className={LABEL}>E-Mail-Adresse</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder="name@beispiel.ch" autoComplete="email" required className={INPUT} />
          </div>
          <div>
            <label className={LABEL}>Benutzername</label>
            <input type="text" value={user} onChange={e => setUser(e.target.value)}
              placeholder="max_muster" autoComplete="username" required className={INPUT} />
          </div>
          <div>
            <label className={LABEL}>Passwort</label>
            <input type="password" value={pw} onChange={e => setPw(e.target.value)}
              placeholder="Min. 8 Zeichen" autoComplete="new-password" required className={INPUT} />
          </div>
          <div>
            <label className={LABEL}>Passwort bestätigen</label>
            <input type="password" value={pw2} onChange={e => setPw2(e.target.value)}
              placeholder="••••••••" autoComplete="new-password" required className={INPUT} />
          </div>
          {err && <div className="px-4 py-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">{err}</div>}
          <button type="submit" disabled={busy}
            className="w-full py-3.5 rounded-lg font-semibold text-sm transition-all disabled:opacity-60 shadow-lg"
            style={{ background: busy ? "#8a9bb0" : "linear-gradient(135deg,#c9a84c,#e8c96a)", color: "#0a1628" }}>
            {busy ? <span className="flex items-center justify-center gap-2"><Spinner /> Registrierung…</span> : "Konto erstellen →"}
          </button>
        </form>

        <div className="mt-5 pt-5 border-t border-slate-100 text-center">
          <p className="text-xs text-slate-400">
            Bereits registriert?{" "}
            <button type="button" onClick={onSwitch} className="font-semibold underline" style={{ color: "#c9a84c" }}>Anmelden</button>
          </p>
        </div>
      </div>
    </div>
  );
}

/* ─── Navbar ─────────────────────────────────────────────────────────── */
function Navbar({ onOpen }: { onOpen: (t: ModalType) => void }) {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const fn = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", fn, { passive: true });
    return () => window.removeEventListener("scroll", fn);
  }, []);

  return (
    <header
      className="fixed top-0 inset-x-0 z-50 transition-all duration-300"
      style={{
        background: scrolled ? "rgba(10,22,40,0.95)" : "rgba(10,22,40,0.7)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        borderBottom: scrolled ? "1px solid rgba(201,168,76,0.2)" : "1px solid transparent",
      }}
    >
      <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
        <a href="#" className="flex items-center gap-2.5 no-underline">
          <Image src="/logo.png" alt="KI-Co-Analyst" width={32} height={32} className="rounded-lg" />
          <span className="font-semibold text-white text-base tracking-tight">KI-Co-Analyst</span>
        </a>

        <nav className="hidden md:flex items-center gap-8">
          <a href="#about" className="text-sm text-slate-300 hover:text-white transition-colors no-underline">Über uns</a>
          <a href="#architecture" className="text-sm text-slate-300 hover:text-white transition-colors no-underline">Architektur</a>
          <button type="button" onClick={() => onOpen("login")}
            className="text-sm text-slate-300 hover:text-white transition-colors cursor-pointer bg-transparent border-none p-0">
            Anmelden
          </button>
          <button type="button" onClick={() => onOpen("register")}
            className="text-sm font-semibold px-4 py-2 rounded-lg transition-all cursor-pointer border-none"
            style={{ background: "linear-gradient(135deg,#c9a84c,#e8c96a)", color: "#0a1628" }}>
            Registrieren
          </button>
        </nav>

        <button type="button" className="md:hidden text-white p-1" onClick={() => setMenuOpen(v => !v)} aria-label="Menu">
          <div className="space-y-1.5">
            <span className={`block w-6 h-0.5 bg-white transition-all ${menuOpen ? "rotate-45 translate-y-2" : ""}`} />
            <span className={`block w-6 h-0.5 bg-white transition-all ${menuOpen ? "opacity-0" : ""}`} />
            <span className={`block w-6 h-0.5 bg-white transition-all ${menuOpen ? "-rotate-45 -translate-y-2" : ""}`} />
          </div>
        </button>
      </div>

      {menuOpen && (
        <div className="md:hidden px-6 pb-4 flex flex-col gap-4 border-t border-white/10">
          <a href="#about" className="text-sm text-slate-300 no-underline" onClick={() => setMenuOpen(false)}>Über uns</a>
          <a href="#architecture" className="text-sm text-slate-300 no-underline" onClick={() => setMenuOpen(false)}>Architektur</a>
          <button type="button" className="text-sm text-slate-300 text-left bg-transparent border-none cursor-pointer"
            onClick={() => { setMenuOpen(false); onOpen("login"); }}>Anmelden</button>
          <button type="button"
            className="text-sm font-semibold px-4 py-2 rounded-lg text-center border-none cursor-pointer"
            style={{ background: "linear-gradient(135deg,#c9a84c,#e8c96a)", color: "#0a1628" }}
            onClick={() => { setMenuOpen(false); onOpen("register"); }}>
            Registrieren
          </button>
        </div>
      )}
    </header>
  );
}

/* ─── Hero ────────────────────────────────────────────────────────────── */
function Hero({ onOpen }: { onOpen: (t: ModalType) => void }) {
  return (
    <section
      className="relative min-h-screen flex flex-col items-center justify-center text-center px-6 pt-16"
      style={{ background: "linear-gradient(160deg, #0a1628 0%, #0f2040 40%, #0a1628 100%)" }}
    >
      <div className="absolute inset-0 opacity-5 pointer-events-none"
        style={{ backgroundImage: "linear-gradient(rgba(201,168,76,0.4) 1px,transparent 1px),linear-gradient(90deg,rgba(201,168,76,0.4) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <div className="absolute pointer-events-none"
        style={{ top:"30%",left:"50%",transform:"translate(-50%,-50%)",width:"700px",height:"700px",
          background:"radial-gradient(circle, rgba(201,168,76,0.08) 0%, transparent 70%)" }} />

      <div className="relative max-w-4xl mx-auto">
        <h1 className="font-serif text-5xl sm:text-6xl lg:text-7xl font-bold text-white leading-tight mb-6">
          Institutionelle Aktienanalyse.{" "}
          <span style={{ color: "#c9a84c" }}>Automatisiert.</span>
        </h1>
        <p className="text-lg sm:text-xl text-slate-300 leading-relaxed max-w-2xl mx-auto mb-10">
          KI-Co-Analyst erstellt in Minuten vollständige Investment-Memos auf Buy-Side-Niveau —
          mit Fundamentalanalyse, DCF-Modellen, Makrokontext und Risikobeurteilung.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <button type="button" onClick={() => onOpen("register")}
            className="px-8 py-3.5 rounded-xl font-semibold text-sm transition-all shadow-lg border-none cursor-pointer"
            style={{ background:"linear-gradient(135deg,#c9a84c,#e8c96a)", color:"#0a1628", boxShadow:"0 0 30px rgba(201,168,76,0.3)" }}>
            Kostenlos starten →
          </button>
          <a href="#comparison"
            className="px-8 py-3.5 rounded-xl font-semibold text-sm transition-all no-underline"
            style={{ border:"1px solid rgba(255,255,255,0.2)", color:"#e2e8f0", background:"rgba(255,255,255,0.04)" }}>
            Vergleich ansehen
          </a>
        </div>
      </div>

      <div className="absolute bottom-8 flex flex-col items-center gap-2 animate-bounce pointer-events-none">
        <span className="text-xs text-slate-500 tracking-widest uppercase">Mehr erfahren</span>
        <svg width="16" height="10" viewBox="0 0 16 10" fill="none">
          <path d="M1 1l7 7 7-7" stroke="#c9a84c" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </div>
    </section>
  );
}

/* ─── Comparison ─────────────────────────────────────────────────────── */
const COMPARISON = [
  { label: "Zeitaufwand",        manual: "3–10 Werktage",           ki: "~3 Minuten" },
  { label: "Datenquellen",       manual: "Manuell recherchiert",    ki: "IR-Dokumente, Makro, News, Konsens" },
  { label: "Bewertungsmodell",   manual: "Excel-Eigenmodell",       ki: "DCF + Multiples + Peer-Vergleich" },
  { label: "Szenarienanalyse",   manual: "Oft nur 1 Szenario",      ki: "Bear / Base / Bull automatisch" },
  { label: "Risikobeurteilung",  manual: "Subjektiv, begrenzt",     ki: "Advocatus Diaboli Agent, Conviction Killers" },
  { label: "Qualitätskontrolle", manual: "Peer Review nötig",       ki: "Supervisor-Agent + Konsistenz-Score" },
  { label: "Skalierbarkeit",     manual: "1–2 Analysen / Woche",    ki: "Unlimitierte Analysen parallel" },
  { label: "Nachvollziehbar",    manual: "Nur intern dokumentiert", ki: "Vollständiges Memo mit Quellenangaben" },
];

function Comparison() {
  return (
    <section id="comparison" className="py-24 px-6" style={{ background:"#f7f8fa" }}>
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-14">
          <div className="text-xs font-bold tracking-widest uppercase mb-3" style={{ color:"#c9a84c" }}>Der Unterschied</div>
          <h2 className="font-serif text-4xl font-bold text-slate-800 mb-4">Manuell vs. KI-Co-Analyst</h2>
          <p className="text-slate-500 max-w-xl mx-auto">
            Was ein erfahrener Analyst in einer Woche erarbeitet, liefert KI-Co-Analyst in Minuten —
            strukturiert, nachvollziehbar und auf institutionellem Niveau.
          </p>
        </div>
        <div className="rounded-2xl overflow-hidden shadow-md border border-slate-200">
          <div className="grid grid-cols-3 text-sm font-bold">
            <div className="px-6 py-4 bg-slate-100 text-slate-500 uppercase tracking-widest text-xs">Kriterium</div>
            <div className="px-6 py-4 bg-red-50 text-red-700 text-center border-l border-slate-200">Manuelle Analyse</div>
            <div className="px-6 py-4 text-center border-l border-slate-200 font-bold" style={{ background:"#0a1628", color:"#c9a84c" }}>KI-Co-Analyst</div>
          </div>
          {COMPARISON.map(({ label, manual, ki }, i) => (
            <div key={label} className="grid grid-cols-3 text-sm border-t border-slate-100"
              style={{ background: i % 2 === 0 ? "#fff" : "#fafafa" }}>
              <div className="px-6 py-4 font-medium text-slate-700">{label}</div>
              <div className="px-6 py-4 text-slate-500 text-center border-l border-slate-100 flex items-center justify-center gap-2">
                <span className="text-red-400">✗</span> {manual}
              </div>
              <div className="px-6 py-4 text-center border-l border-slate-100 flex items-center justify-center gap-2 font-medium text-slate-800">
                <span className="text-emerald-500">✓</span> {ki}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Benefits ───────────────────────────────────────────────────────── */
const BENEFITS = [
  { icon:"⚡", title:"Blitzschnelle Resultate",  desc:"Von Ticker-Eingabe bis zum vollständigen Investment-Memo in unter 5 Minuten." },
  { icon:"🏦", title:"Buy-Side Qualität",         desc:"DCF, EV/EBITDA-Vergleiche, Peer-Benchmarks und Makro-Einordnung auf institutionellem Standard." },
  { icon:"🧠", title:"9 spezialisierte Agenten",  desc:"Jeder Agent übernimmt eine dedizierte Aufgabe – von Klassifikation bis zur finalen Qualitätsprüfung." },
  { icon:"⚖️", title:"Integrierter Advocatus",   desc:"Ein dedizierter Risiko-Agent hinterfragt jede These aktiv und identifiziert Conviction Killers." },
  { icon:"📂", title:"Analyse-Archiv",            desc:"Alle Analysen werden gespeichert und sind jederzeit abrufbar – mit Filterfunktion." },
  { icon:"🔒", title:"Sicher & Privat",           desc:"Betrieb auf eigener Infrastruktur, keine Datenweitergabe. Zugangskontrolle per Login." },
];

function Benefits() {
  return (
    <section id="about" className="py-24 px-6 bg-white">
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-14">
          <div className="text-xs font-bold tracking-widest uppercase mb-3" style={{ color:"#c9a84c" }}>Warum KI-Co-Analyst</div>
          <h2 className="font-serif text-4xl font-bold text-slate-800 mb-4">Analyse ohne Kompromisse</h2>
          <p className="text-slate-500 max-w-xl mx-auto">
            KI-Co-Analyst kombiniert modernste Sprachmodelle mit strukturierten Finanzmodellen —
            für Research, das sich nach Goldman Sachs anfühlt, nicht nach ChatGPT.
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {BENEFITS.map(({ icon, title, desc }) => (
            <div key={title} className="p-6 rounded-2xl border border-slate-100 hover:border-slate-200 hover:shadow-md transition-all"
              style={{ background:"#fafafa" }}>
              <div className="text-3xl mb-4">{icon}</div>
              <h3 className="font-semibold text-slate-800 mb-2">{title}</h3>
              <p className="text-sm text-slate-500 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Architecture ───────────────────────────────────────────────────── */
const AGENTS = [
  { icon:"🏷️", name:"Classifier",        desc:"Geschäftsmodell-Klassifikation & Peer-Gruppen" },
  { icon:"🔍", name:"Fundamental",        desc:"IR-Dokumente · DCF · Multiples · Bilanz" },
  { icon:"📰", name:"News & Sentiment",   desc:"Makro · Branchentrends · Nachrichten" },
  { icon:"📐", name:"Estimate Revision",  desc:"Makro-adjustierte Konsensschätzungen" },
  { icon:"🌐", name:"Thematic",           desc:"Megatrends · Adoptionskurven · Positionierung" },
  { icon:"🎲", name:"Optionality",        desc:"Real Options · Pre-Revenue-Bewertung" },
  { icon:"📈", name:"Forward Estimates",  desc:"Wachstums-Projektion · Szenarienmodell" },
  { icon:"⚖️", name:"Risk / Advocatus",  desc:"Gegenposition · Conviction Killers" },
  { icon:"✍️", name:"Supervisor",         desc:"Synthese · Qualitätsprüfung · Final Memo" },
];

function Architecture() {
  return (
    <section id="architecture" className="py-24 px-6" style={{ background:"#0a1628" }}>
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-14">
          <div className="text-xs font-bold tracking-widest uppercase mb-3" style={{ color:"#c9a84c" }}>Unter der Haube</div>
          <h2 className="font-serif text-4xl font-bold text-white mb-4">9-Agenten Pipeline</h2>
          <p className="text-slate-400 max-w-xl mx-auto">
            Jede Analyse durchläuft sequenziell neun spezialisierte KI-Agenten.
            Der Supervisor-Agent fasst alle Ergebnisse zu einem kohärenten Investment-Memo zusammen.
          </p>
        </div>
        <div className="space-y-3">
          {AGENTS.map(({ icon, name, desc }, i) => {
            const isSup = i === AGENTS.length - 1;
            return (
              <div key={name} className="flex items-center gap-4 p-4 rounded-xl border"
                style={isSup
                  ? { background:"rgba(201,168,76,0.06)", borderColor:"rgba(201,168,76,0.4)" }
                  : { background:"rgba(255,255,255,0.03)", borderColor:"rgba(255,255,255,0.08)" }}>
                <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold"
                  style={isSup
                    ? { background:"linear-gradient(135deg,#c9a84c,#e8c96a)", color:"#0a1628" }
                    : { background:"rgba(255,255,255,0.08)", color:"#8a9bb0" }}>{i + 1}</div>
                <div className="text-2xl w-8 text-center flex-shrink-0">{icon}</div>
                <div className="flex-1">
                  <div className="font-semibold text-sm" style={{ color: isSup ? "#c9a84c" : "#fff" }}>{name}</div>
                  <div className="text-xs text-slate-400 mt-0.5">{desc}</div>
                </div>
                {isSup && (
                  <div className="hidden sm:block px-3 py-1 rounded-full text-xs font-semibold"
                    style={{ background:"rgba(201,168,76,0.15)", color:"#c9a84c" }}>Final Output</div>
                )}
              </div>
            );
          })}
        </div>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
          {["Investment-Memo","DCF-Modell","Peer-Vergleich","Szenarien","Conviction-Score"].map(t => (
            <div key={t} className="px-4 py-1.5 rounded-full text-xs font-medium"
              style={{ background:"rgba(201,168,76,0.1)", color:"#c9a84c", border:"1px solid rgba(201,168,76,0.25)" }}>{t}</div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── CTA Banner ─────────────────────────────────────────────────────── */
function CTABanner({ onOpen }: { onOpen: (t: ModalType) => void }) {
  return (
    <section className="py-20 px-6" style={{ background:"#f7f8fa" }}>
      <div className="max-w-3xl mx-auto text-center">
        <h2 className="font-serif text-4xl font-bold text-slate-800 mb-4">Bereit für professionelles Research?</h2>
        <p className="text-slate-500 mb-8">Starten Sie noch heute und erhalten Sie Ihre erste Aktienanalyse in unter 5 Minuten.</p>
        <button type="button" onClick={() => onOpen("register")}
          className="px-10 py-4 rounded-xl font-bold text-sm transition-all shadow-lg border-none cursor-pointer"
          style={{ background:"linear-gradient(135deg,#c9a84c,#e8c96a)", color:"#0a1628", boxShadow:"0 8px 30px rgba(201,168,76,0.3)" }}>
          Jetzt kostenlos registrieren →
        </button>
        <p className="text-xs text-slate-400 mt-4">Keine Kreditkarte · Sofortzugang · Eigene Infrastruktur</p>
      </div>
    </section>
  );
}

/* ─── Footer ─────────────────────────────────────────────────────────── */
function Footer({ onOpen }: { onOpen: (t: ModalType) => void }) {
  return (
    <footer style={{ background:"#0a1628", borderTop:"1px solid rgba(255,255,255,0.08)" }}>
      <div className="max-w-6xl mx-auto px-6 py-14">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-10">
          <div>
            <div className="flex items-center gap-2.5 mb-4">
              <Image src="/logo.png" alt="KI-Co-Analyst" width={32} height={32} className="rounded-lg" />
              <span className="font-semibold text-white">KI-Co-Analyst</span>
            </div>
            <p className="text-xs text-slate-500 leading-relaxed">
              Institutionelle Aktienanalyse, automatisiert durch einen Multi-Agenten-Workflow.
            </p>
          </div>
          <div>
            <div className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-4">Produkt</div>
            <ul className="space-y-2.5">
              <li><a href="#about" className="text-sm text-slate-400 hover:text-white transition-colors no-underline">Über uns</a></li>
              <li><a href="#architecture" className="text-sm text-slate-400 hover:text-white transition-colors no-underline">Architektur</a></li>
              <li><a href="#comparison" className="text-sm text-slate-400 hover:text-white transition-colors no-underline">Vergleich</a></li>
              <li>
                <button type="button" onClick={() => onOpen("login")}
                  className="text-sm text-slate-400 hover:text-white transition-colors bg-transparent border-none cursor-pointer p-0">
                  Anmelden
                </button>
              </li>
            </ul>
          </div>
          <div>
            <div className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-4">Rechtliches</div>
            <ul className="space-y-2.5">
              {["Disclaimer","Datenschutz","Impressum","AGB"].map(label => (
                <li key={label}><a href="#" className="text-sm text-slate-400 hover:text-white transition-colors no-underline">{label}</a></li>
              ))}
            </ul>
          </div>
          <div className="p-4 rounded-xl text-xs text-slate-500 leading-relaxed"
            style={{ background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)" }}>
            <strong className="text-slate-400 block mb-1">⚠️ Haftungsausschluss</strong>
            Die Inhalte dienen ausschliesslich zu Informationszwecken und stellen keine Anlageberatung dar.
          </div>
        </div>
        <div className="mt-10 pt-6 flex flex-col sm:flex-row items-center justify-between gap-3"
          style={{ borderTop:"1px solid rgba(255,255,255,0.06)" }}>
          <p className="text-xs text-slate-600">© {new Date().getFullYear()} KI-Co-Analyst. Alle Rechte vorbehalten.</p>
          <p className="text-xs text-slate-600">Entwickelt in der Schweiz 🇨🇭</p>
        </div>
      </div>
    </footer>
  );
}

/* ─── Page (modal state lives here) ─────────────────────────────────── */
export default function Landing() {
  const router = useRouter();
  const [modal, setModal] = useState<ModalType>("none");

  const open  = useCallback((t: ModalType) => setModal(t), []);
  const close = useCallback(() => setModal("none"), []);

  // ESC key + body scroll lock
  useEffect(() => {
    if (modal === "none") return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [modal, close]);

  const handleLoginSuccess = useCallback(() => {
    close();
    router.push("/dashboard");
  }, [close, router]);

  return (
    <>
      <Navbar onOpen={open} />
      <Hero   onOpen={open} />
      <Comparison />
      <Benefits />
      <Architecture />
      <CTABanner onOpen={open} />
      <Footer    onOpen={open} />

      {/* Modal overlay — always in DOM, shown/hidden via conditional */}
      {modal !== "none" && (
        <div
          className="fixed inset-0 flex items-center justify-center p-4"
          style={{ background:"rgba(10,22,40,0.8)", backdropFilter:"blur(6px)", zIndex:200 }}
          onClick={(e) => { if (e.target === e.currentTarget) close(); }}
        >
          {modal === "login" && (
            <LoginForm
              onClose={close}
              onSwitch={() => setModal("register")}
              onSuccess={handleLoginSuccess}
            />
          )}
          {modal === "register" && (
            <RegisterForm
              onClose={close}
              onSwitch={() => setModal("login")}
            />
          )}
        </div>
      )}
    </>
  );
}
