"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { login } from "@/lib/api";
import { Wordmark } from "@/components/brand/Brand";

const INPUT = "w-full h-12 px-3.5 border border-line-3 rounded-[2px] bg-white text-[15px] text-ink outline-none focus:border-gold";

export default function LoginPage() {
  const router = useRouter();
  const [user, setUser] = useState("");
  const [pw, setPw]     = useState("");
  const [err, setErr]   = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      await login(user.trim(), pw);
      router.push("/dashboard");
    } catch {
      setErr("Ungültige Anmeldedaten.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen dot-grid flex items-center justify-center p-5">
      <div className="w-full max-w-md flex flex-col gap-8">
        <Link href="/" className="font-mono text-[11px] tracking-[0.1em] no-underline">← STARTSEITE</Link>
        <Wordmark />
        <form onSubmit={handleSubmit}
          className="bg-card border border-line p-8 flex flex-col gap-5 shadow-[0_30px_60px_-40px_rgba(60,45,10,0.35)]">
          <h1 className="m-0 font-display font-normal text-[40px] leading-none">Anmelden</h1>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="login-user" className="label-mono">Benutzername</label>
            <input id="login-user" type="text" value={user} onChange={e => setUser(e.target.value)}
              autoComplete="username" required className={INPUT} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="login-pw" className="label-mono">Passwort</label>
            <input id="login-pw" type="password" value={pw} onChange={e => setPw(e.target.value)}
              autoComplete="current-password" required className={INPUT} />
          </div>
          {err && <div role="alert" className="px-4 py-3 text-sm border border-negative/40 text-negative bg-[#FBEFEF]">{err}</div>}
          <button type="submit" disabled={loading}
            className="h-12 rounded-[2px] bg-ink text-cream text-[15px] font-semibold disabled:opacity-60">
            {loading ? "Anmelden …" : "Anmelden"}
          </button>
        </form>
        <p className="m-0 text-xs text-muted">Keine Anlageberatung im Sinne von Art. 3 lit. c FIDLEG.</p>
      </div>
    </div>
  );
}
