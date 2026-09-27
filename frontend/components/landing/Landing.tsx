"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { login as apiLogin, register as apiRegister } from "@/lib/api";
import { LogoMark, Wordmark } from "@/components/brand/Brand";
import { AGENT_COUNT_LLM, GRAPH_NODE_COUNT } from "@/lib/pipeline";
import PipelineGraph from "./PipelineGraph";

type ModalType = "none" | "login" | "register";

// Kontaktadresse für "Demo anfragen" — ohne gesetzte Variable führt der Button
// zur Registrierung statt zu einem toten mailto-Link.
const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL ?? "";

const INPUT = "w-full h-12 px-3.5 border border-line-3 rounded-[2px] bg-white text-[15px] text-ink outline-none focus:border-gold";
const BTN_DARK = "inline-flex items-center justify-center h-14 px-7 bg-ink text-cream font-semibold text-base rounded-[2px] no-underline hover:text-cream";
const BTN_LINE = "inline-flex items-center justify-center h-14 px-7 border border-gold text-ink font-semibold text-base rounded-[2px] no-underline hover:text-ink";

/* ─── Dialoge ─────────────────────────────────────────────────────────── */

function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="bg-card border border-line w-full max-w-md p-8 flex flex-col gap-5 shadow-[0_40px_80px_-40px_rgba(60,45,10,0.5)]"
      role="dialog" aria-modal="true" aria-labelledby="dlg-title">
      <div className="flex justify-between items-start">
        <h2 id="dlg-title" className="m-0 font-display font-normal text-[40px] leading-none">{title}</h2>
        <button type="button" onClick={onClose} aria-label="Schliessen"
          className="w-11 h-11 -mr-3 -mt-2 text-2xl text-muted hover:text-ink">×</button>
      </div>
      {children}
    </div>
  );
}

function Field({ id, label, ...props }: { id: string; label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="label-mono">{label}</label>
      <input id={id} className={INPUT} {...props} />
    </div>
  );
}

function LoginForm({ onClose, onSwitch, onSuccess }: { onClose: () => void; onSwitch: () => void; onSuccess: () => void }) {
  const [user, setUser] = useState("");
  const [pw, setPw]     = useState("");
  const [err, setErr]   = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
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
  }

  return (
    <Dialog title="Anmelden" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field id="lg-user" label="Benutzername" value={user} onChange={e => setUser(e.target.value)} autoComplete="username" required />
        <Field id="lg-pw" label="Passwort" type="password" value={pw} onChange={e => setPw(e.target.value)} autoComplete="current-password" required />
        {err && <div role="alert" className="px-4 py-3 text-sm border border-negative/40 text-negative bg-[#FBEFEF]">{err}</div>}
        <button type="submit" disabled={busy} className="h-12 bg-ink text-cream font-semibold rounded-[2px] disabled:opacity-60">
          {busy ? "Anmelden …" : "Anmelden"}
        </button>
      </form>
      <p className="m-0 pt-4 border-t border-line text-sm text-muted">
        Noch kein Konto? <button type="button" onClick={onSwitch} className="font-semibold text-gold-text underline">Registrieren</button>
      </p>
    </Dialog>
  );
}

function RegisterForm({ onClose, onSwitch }: { onClose: () => void; onSwitch: () => void }) {
  const [email, setEmail] = useState("");
  const [user, setUser]   = useState("");
  const [pw, setPw]       = useState("");
  const [pw2, setPw2]     = useState("");
  const [err, setErr]     = useState("");
  const [ok, setOk]       = useState(false);
  const [busy, setBusy]   = useState(false);

  async function submit(e: React.FormEvent) {
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
  }

  if (ok) {
    return (
      <Dialog title="Konto erstellt" onClose={onClose}>
        <p className="m-0 text-[15px] text-ink-2">Sie können sich jetzt anmelden.</p>
        <button type="button" onClick={onSwitch} className="h-12 bg-ink text-cream font-semibold rounded-[2px]">Jetzt anmelden</button>
      </Dialog>
    );
  }

  return (
    <Dialog title="Registrieren" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field id="rg-mail" label="E-Mail" type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" required />
        <Field id="rg-user" label="Benutzername" value={user} onChange={e => setUser(e.target.value)} autoComplete="username" required />
        <Field id="rg-pw" label="Passwort (min. 8 Zeichen)" type="password" value={pw} onChange={e => setPw(e.target.value)} autoComplete="new-password" required />
        <Field id="rg-pw2" label="Passwort bestätigen" type="password" value={pw2} onChange={e => setPw2(e.target.value)} autoComplete="new-password" required />
        {err && <div role="alert" className="px-4 py-3 text-sm border border-negative/40 text-negative bg-[#FBEFEF]">{err}</div>}
        <button type="submit" disabled={busy} className="h-12 bg-ink text-cream font-semibold rounded-[2px] disabled:opacity-60">
          {busy ? "Registrierung …" : "Konto erstellen"}
        </button>
      </form>
      <p className="m-0 pt-4 border-t border-line text-sm text-muted">
        Bereits registriert? <button type="button" onClick={onSwitch} className="font-semibold text-gold-text underline">Anmelden</button>
      </p>
    </Dialog>
  );
}

/* ─── Abschnitte ──────────────────────────────────────────────────────── */

function DemoButton({ onRegister, className }: { onRegister: () => void; className: string }) {
  return CONTACT_EMAIL
    ? <a href={`mailto:${CONTACT_EMAIL}?subject=Demo%20KI-Co-Analyst`} className={className}>Demo anfragen</a>
    : <button type="button" onClick={onRegister} className={className}>Zugang anfragen</button>;
}

function Nav({ onOpen }: { onOpen: (t: ModalType) => void }) {
  const [open, setOpen] = useState(false);
  const links = [["#pipeline", "Pipeline"], ["#agenten", "So funktioniert es"], ["#methodik", "Methodik"], ["#kontakt", "Für Banken"]];
  return (
    <header className="border-b border-line">
      <div className="h-20 px-5 md:px-20 flex items-center justify-between">
        <a href="#" className="no-underline" aria-label="KI-Co-Analyst Startseite"><Wordmark /></a>
        <nav aria-label="Seitennavigation" className="hidden lg:flex items-center gap-10 text-[15px]">
          {links.map(([h, l]) => <a key={h} href={h} className="text-ink-2 no-underline hover:text-ink">{l}</a>)}
          <button type="button" onClick={() => onOpen("login")} className="text-ink-2 hover:text-ink">Anmelden</button>
          <DemoButton onRegister={() => onOpen("register")}
            className="inline-flex items-center h-11 px-5 bg-ink text-cream font-semibold rounded-[2px] no-underline hover:text-cream" />
        </nav>
        <button type="button" className="lg:hidden w-11 h-11 text-ink" onClick={() => setOpen(v => !v)}
          aria-label={open ? "Menü schliessen" : "Menü öffnen"} aria-expanded={open}>
          <span className="block w-6 h-px bg-ink mx-auto mb-1.5" /><span className="block w-6 h-px bg-ink mx-auto mb-1.5" /><span className="block w-6 h-px bg-ink mx-auto" />
        </button>
      </div>
      {open && (
        <div className="lg:hidden px-5 pb-5 flex flex-col gap-1 border-t border-line">
          {links.map(([h, l]) => <a key={h} href={h} onClick={() => setOpen(false)} className="py-2.5 text-ink-2 no-underline">{l}</a>)}
          <button type="button" onClick={() => { setOpen(false); onOpen("login"); }} className="py-2.5 text-left text-ink-2">Anmelden</button>
        </div>
      )}
    </header>
  );
}

function Certificate() {
  return (
    <svg viewBox="0 0 500 600" className="w-[460px] max-w-full h-auto rotate-3 drop-shadow-[0_30px_40px_rgba(60,45,10,0.18)]"
      role="img" aria-label="Illustration eines historischen Aktienzertifikats">
      <rect x="0" y="0" width="500" height="600" fill="#FFFDF6" stroke="#B08D3C" strokeWidth="1.5" />
      <rect x="14" y="14" width="472" height="572" fill="none" stroke="#B08D3C" strokeWidth="0.8" />
      <rect x="22" y="22" width="456" height="556" fill="none" stroke="#C9A24A" strokeWidth="1" strokeDasharray="1 3" />
      <g fill="#B08D3C">
        {[[14, 14], [486, 14], [14, 586], [486, 586]].map(([cx, cy]) => (
          <rect key={`${cx}-${cy}`} x={cx - 4} y={cy - 4} width="8" height="8" transform={`rotate(45 ${cx} ${cy})`} />
        ))}
      </g>
      <g fill="none" stroke="#C9A24A" strokeWidth="0.6">
        {Array.from({ length: 18 }, (_, i) => (
          <ellipse key={i} cx="250" cy="170" rx="62" ry="22" transform={`rotate(${i * 10} 250 170)`} />
        ))}
        <circle cx="250" cy="170" r="70" />
        <circle cx="250" cy="170" r="76" strokeDasharray="2 2" />
      </g>
      <circle cx="250" cy="170" r="14" fill="#B08D3C" />
      <text x="250" y="292" textAnchor="middle" fontFamily="var(--font-instrument), Georgia, serif" fontSize="60" letterSpacing="18" fill="#121417">AKTIE</text>
      <text x="250" y="322" textAnchor="middle" fontFamily="var(--font-jetbrains), monospace" fontSize="11" letterSpacing="2" fill="#7F6320">NAMENAKTIE · NR. 000021</text>
      <line x1="150" y1="342" x2="350" y2="342" stroke="#C9A24A" strokeWidth="0.8" />
      <text x="250" y="378" textAnchor="middle" fontFamily="var(--font-instrument), Georgia, serif" fontStyle="italic" fontSize="26" fill="#121417">Muster Robotics AG</text>
      <g fill="#E6DDC7">
        <rect x="70" y="404" width="360" height="3" /><rect x="90" y="416" width="320" height="3" />
        <rect x="70" y="428" width="360" height="3" /><rect x="120" y="440" width="260" height="3" />
      </g>
      <path d="M62 520 C 80 490, 95 530, 110 505 S 140 500, 150 515 S 180 505, 200 508" fill="none" stroke="#121417" strokeWidth="1.2" />
      <line x1="60" y1="534" x2="210" y2="534" stroke="#B08D3C" strokeWidth="0.8" />
      <text x="60" y="552" fontFamily="var(--font-jetbrains), monospace" fontSize="9" letterSpacing="1.5" fill="#6A6D72">DER VERWALTUNGSRAT</text>
      <circle cx="400" cy="515" r="42" fill="none" stroke="#B08D3C" strokeWidth="1.2" />
      <circle cx="400" cy="515" r="34" fill="none" stroke="#C9A24A" strokeWidth="0.8" strokeDasharray="2 2" />
      <text x="400" y="524" textAnchor="middle" fontFamily="var(--font-instrument), Georgia, serif" fontSize="28" fill="#9A7A2E">KI</text>
    </svg>
  );
}

const CHART = "0,146 10,139 20,140 30,132 40,131 50,127 60,119 70,118 80,110 90,107 100,99 110,91 120,89 130,92 140,85 150,79 160,80 170,85 180,85 190,82 200,87 210,79 220,83 230,78 240,71 250,64 260,60 270,63 280,57 290,56 300,57";

function Hero({ onRegister }: { onRegister: () => void }) {
  return (
    <section className="dot-grid px-5 md:px-20 pt-16 lg:pt-24 pb-16 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_600px] gap-12 lg:min-h-[820px]">
      <div className="flex flex-col gap-8 lg:pt-6">
        <div className="eyebrow">MULTI-AGENT EQUITY RESEARCH</div>
        <h1 className="m-0 font-display font-normal text-6xl md:text-[96px] leading-[0.98] tracking-[-0.025em] text-balance">
          Aktienanalyse, geprüft von <em className="text-gold-dark">{AGENT_COUNT_LLM} KI-Agenten.</em>
        </h1>
        <p className="m-0 text-xl leading-relaxed text-ink-2 max-w-[560px] text-pretty">
          Der KI-Co-Analyst verbindet Fundamental-, Schätzungs-, Makro- und Themenanalyse zu einem gewichteten
          Urteil – nachvollziehbar bis zum einzelnen Agenten. Für Research-Teams und Portfolio-Manager.
        </p>
        <div className="flex flex-wrap gap-4">
          <DemoButton onRegister={onRegister} className={BTN_DARK} />
          <a href="#methodik" className={BTN_LINE}>Methodik ansehen</a>
        </div>
      </div>

      <div className="relative min-h-[520px] lg:h-[620px]">
        <div className="absolute right-0 top-0 w-[88%] lg:w-auto"><Certificate /></div>
        <div className="absolute left-0 bottom-0 w-[340px] max-w-full p-5 bg-card border border-line shadow-[0_30px_60px_-28px_rgba(60,45,10,0.35)] flex flex-col gap-3">
          <div className="flex justify-between font-mono text-[11px] tracking-[0.08em] text-muted-2"><span>MRBT · 1 JAHR</span><span>BEISPIEL</span></div>
          <svg viewBox="0 0 300 170" className="w-full h-[130px]" role="img" aria-label="Kursverlauf (Beispiel)" preserveAspectRatio="none">
            <line x1="0" y1="60" x2="300" y2="60" stroke="#E4DCC8" strokeDasharray="3 4" />
            <line x1="0" y1="110" x2="300" y2="110" stroke="#E4DCC8" strokeDasharray="3 4" />
            <polygon points={`${CHART} 300,170 0,170`} fill="#EFE3C2" opacity="0.7" />
            <polyline points={CHART} fill="none" stroke="#9A7A2E" strokeWidth="2" />
            <circle cx="300" cy="57" r="4" fill="#121417" />
          </svg>
          <div className="flex items-baseline justify-between gap-3 pt-2.5 border-t border-line">
            <div className="font-display text-[28px]">Übergewichten</div>
            <div className="font-mono text-[10px] tracking-[0.08em] text-gold-text whitespace-nowrap">GEWICHTET</div>
          </div>
        </div>
      </div>
    </section>
  );
}

function FactStrip() {
  const facts = [
    [`${GRAPH_NODE_COUNT} Knoten`, "Multi-Agent-Graph auf LangGraph"],
    ["Konfidenz-gewichtet", "Deterministische Aggregation im Supervisor"],
    ["Voller Trace", "Jeder Schritt einsehbar und prüfbar"],
    ["Made in Bern", "Entwickelt an der Berner Fachhochschule"],
  ];
  return (
    <section className="px-5 md:px-20 border-y border-line bg-card grid grid-cols-2 lg:grid-cols-4">
      {facts.map(([t, s], i) => (
        <div key={t} className={`py-8 flex flex-col gap-1.5 ${i > 0 ? "lg:pl-8 lg:border-l lg:border-line" : ""} ${i % 2 === 1 ? "pl-6 border-l border-line lg:pl-8" : ""}`}>
          <div className="font-display text-[30px]">{t}</div>
          <div className="text-sm text-muted">{s}</div>
        </div>
      ))}
    </section>
  );
}

function Pipeline() {
  return (
    <section id="pipeline" className="px-5 md:px-20 pt-24 lg:pt-36 flex flex-col gap-12">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-20 items-end">
        <div className="flex flex-col gap-5">
          <div className="eyebrow plain">DIE PIPELINE</div>
          <h2 className="m-0 font-display font-normal text-5xl md:text-[64px] leading-[1.02] tracking-[-0.02em]">
            Alle Verbindungen. <em className="text-gold-dark">Auf einen Blick.</em>
          </h2>
        </div>
        <p className="m-0 text-lg leading-relaxed text-ink-2 text-pretty">
          Vom Ticker bis zum Memo: in welcher Reihenfolge die Agenten arbeiten, wo Prüfschleifen greifen und wie
          der Senior Review gezielt Kritik zurückspielt, bevor der Supervisor das Urteil formuliert.
        </p>
      </div>
      <div className="bg-card border border-line p-6 md:p-10 flex flex-col gap-6 shadow-[0_40px_80px_-60px_rgba(60,45,10,0.35)]">
        <div className="overflow-x-auto"><PipelineGraph /></div>
        <div className="flex flex-wrap gap-x-8 gap-y-3 items-center pt-5 border-t border-line text-[13px] text-muted">
          {[
            ["#B08D3C", undefined, "Ablauf"],
            ["#C9A24A", "7 5", "Bedingte Verzweigung"],
            ["#8B8E93", "2 4", "Retry-Schleife"],
          ].map(([c, dash, l]) => (
            <div key={l} className="flex items-center gap-2.5">
              <svg width="32" height="6" aria-hidden="true"><line x1="0" y1="3" x2="32" y2="3" stroke={c} strokeWidth="1.5" strokeDasharray={dash} /></svg>{l}
            </div>
          ))}
          <div className="lg:ml-auto font-mono text-[11px] tracking-[0.08em]">LANGGRAPH · {GRAPH_NODE_COUNT} KNOTEN</div>
        </div>
      </div>
    </section>
  );
}

function HowItWorks() {
  const steps = [
    ["01", "Klassifizieren", "Der Business Model Classifier ordnet das Unternehmen ein und bestimmt, welche Methoden überhaupt gelten."],
    ["02", "Analysieren", "Fundamental, News, Estimate Revision, Thematic, Optionality, Forward Estimate und Risk – mit Anomalie-Check und automatischen Retries."],
    ["03", "Prüfen", "Quality-Check und Senior Review. Bei Schwächen geht gezielte Kritik zurück an Fundamental, News oder Risk."],
    ["04", "Synthese", "Der Supervisor gewichtet nach Konfidenz und liefert das Memo: Empfehlung, Conviction und Routing-Log."],
  ];
  return (
    <section id="agenten" className="px-5 md:px-20 pt-24 lg:pt-36 pb-24 lg:pb-32 flex flex-col gap-16">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-20 items-end">
        <div className="flex flex-col gap-5">
          <div className="eyebrow plain">SO FUNKTIONIERT ES</div>
          <h2 className="m-0 font-display font-normal text-5xl md:text-[64px] leading-[1.02] tracking-[-0.02em]">
            Ein Research-Team aus Spezialisten. <em className="text-gold-dark">In Minuten.</em>
          </h2>
        </div>
        <p className="m-0 text-lg leading-relaxed text-ink-2 text-pretty">
          Statt eines einzelnen Modells arbeiten spezialisierte Agenten Schritt für Schritt – jeder baut auf den
          Ergebnissen des vorherigen auf. Ein Senior Review prüft, ein Supervisor entscheidet.
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 border-t border-ink">
        {steps.map(([n, t, p], i) => (
          <div key={n} className={`pt-8 pb-4 flex flex-col gap-4 lg:pr-8 ${i > 0 ? "lg:pl-8 lg:border-l lg:border-line" : ""}`}>
            <div className="font-mono text-[13px] text-gold-dark">{n}</div>
            <h3 className="m-0 font-display font-normal text-[32px]">{t}</h3>
            <p className="m-0 text-base leading-relaxed text-ink-2">{p}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function Methodik() {
  const items = [
    ["I", "Vollständige Transparenz", `Jeder der ${GRAPH_NODE_COUNT} Knoten landet im Routing-Log: welcher Pfad genommen wurde, welche Retries und welche Kritik-Runde.`],
    ["II", "Methodische Disziplin", "Die Klassifikation verhindert falsche Werkzeuge – etwa ein DCF für Unternehmen ohne Umsatz."],
    ["III", "Wissenschaftlich fundiert", "Entwickelt und verteidigt als Bachelorthesis an der Berner Fachhochschule, gestützt auf eine Analyse von über zwölf KI-Research-Systemen."],
  ];
  return (
    <section id="methodik" className="px-5 md:px-20 py-24 lg:py-32 bg-ink text-cream-2 grid grid-cols-1 lg:grid-cols-[480px_minmax(0,1fr)] gap-12 lg:gap-24">
      <div className="flex flex-col gap-6">
        <div className="font-mono text-xs tracking-[0.14em] text-gold-dim">METHODIK &amp; VERTRAUEN</div>
        <h2 className="m-0 font-display font-normal text-5xl md:text-[60px] leading-[1.04] tracking-[-0.02em]">
          Keine Blackbox. <em className="text-gold-dim">Ein Co-Analyst.</em>
        </h2>
        <p className="m-0 text-lg leading-relaxed text-dark-muted">
          Entscheidungen bleiben beim Menschen. Der KI-Co-Analyst liefert die Grundlage – begründet, gewichtet und überprüfbar.
        </p>
      </div>
      <div className="flex flex-col">
        {items.map(([n, t, p], i) => (
          <div key={n} className={`grid grid-cols-[64px_minmax(0,1fr)] gap-6 py-8 border-t border-dark-line ${i === items.length - 1 ? "border-b" : ""}`}>
            <div className="font-mono text-[13px] text-gold-dim pt-2">{n}</div>
            <div className="flex flex-col gap-2">
              <h3 className="m-0 font-display font-normal text-[30px]">{t}</h3>
              <p className="m-0 text-base leading-relaxed text-dark-muted">{p}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Kontakt({ onRegister }: { onRegister: () => void }) {
  return (
    <section id="kontakt" className="px-5 md:px-20 pt-24 lg:pt-36 pb-20 flex flex-col items-center gap-7 text-center">
      <LogoMark size={28} />
      <h2 className="m-0 font-display font-normal text-5xl md:text-[72px] leading-[1.02] tracking-[-0.02em] max-w-[900px] text-balance">
        Bereit für einen Pilot mit Ihrem <em className="text-gold-dark">Research-Team?</em>
      </h2>
      <p className="m-0 text-lg leading-relaxed text-ink-2 max-w-[560px]">
        Wir zeigen den KI-Co-Analysten an Titeln aus Ihrem Coverage-Universum.
      </p>
      <DemoButton onRegister={onRegister} className={BTN_DARK} />
      <footer className="mt-16 w-full pt-8 border-t border-line flex flex-wrap justify-between gap-3 text-sm text-muted">
        <span>© {new Date().getFullYear()} KI-Co-Analyst · Luca Lüdi · Keine Anlageberatung (Art. 3 lit. c FIDLEG)</span>
        <span className="font-mono text-xs tracking-[0.08em]">BERN · SCHWEIZ</span>
      </footer>
    </section>
  );
}

/* ─── Seite ───────────────────────────────────────────────────────────── */

export default function Landing() {
  const router = useRouter();
  const [modal, setModal] = useState<ModalType>("none");
  const open  = useCallback((t: ModalType) => setModal(t), []);
  const close = useCallback(() => setModal("none"), []);

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

  return (
    <div className="bg-paper text-ink">
      <Nav onOpen={open} />
      <Hero onRegister={() => open("register")} />
      <FactStrip />
      <Pipeline />
      <HowItWorks />
      <Methodik />
      <Kontakt onRegister={() => open("register")} />

      {modal !== "none" && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-ink/70 backdrop-blur-sm"
          onClick={e => { if (e.target === e.currentTarget) close(); }}>
          {modal === "login" && (
            <LoginForm onClose={close} onSwitch={() => setModal("register")} onSuccess={() => { close(); router.push("/dashboard"); }} />
          )}
          {modal === "register" && <RegisterForm onClose={close} onSwitch={() => setModal("login")} />}
        </div>
      )}
    </div>
  );
}
