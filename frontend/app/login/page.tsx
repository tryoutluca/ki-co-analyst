"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { login } from "@/lib/api";

export default function LoginPage() {
  const router  = useRouter();
  const [user, setUser]   = useState("");
  const [pw,   setPw]     = useState("");
  const [err,  setErr]    = useState("");
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
    <div className="min-h-screen flex items-center justify-center p-4 bg-[#0a1628]">

      <div className="relative w-full max-w-md">

        {/* Back button */}
        <div className="mb-6">
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-sm no-underline transition-colors"
            style={{ color: "#8a9bb0" }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M10 12L6 8l4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Zurück zur Startseite
          </Link>
        </div>

        {/* Logo */}
        <div className="text-center mb-10">
          <Image src="/logo.png" alt="KI-Co-Analyst" width={64} height={64}
                 className="mx-auto mb-4 rounded-xl" />
          <h1 className="text-3xl font-bold text-white mb-2 tracking-tight">
            KI-Co-Analyst
          </h1>
          <p className="text-sm tracking-widest uppercase"
             style={{ color: "#8a9bb0" }}>
            Equity Research Platform
          </p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl overflow-hidden">

          <form onSubmit={handleSubmit} className="p-8 space-y-5">
            <div>
              <label className="block text-xs font-semibold tracking-widest uppercase mb-2"
                     style={{ color: "#8a9bb0" }}>
                Benutzername
              </label>
              <input
                type="text"
                value={user}
                onChange={e => setUser(e.target.value)}
                placeholder="admin"
                autoComplete="username"
                required
                className="w-full px-4 py-3 rounded-lg border text-sm outline-none transition-all
                           border-slate-200 focus:border-blue-400 focus:ring-2 focus:ring-blue-100
                           bg-slate-50 text-slate-800 placeholder-slate-400"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold tracking-widest uppercase mb-2"
                     style={{ color: "#8a9bb0" }}>
                Passwort
              </label>
              <input
                type="password"
                value={pw}
                onChange={e => setPw(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
                required
                className="w-full px-4 py-3 rounded-lg border text-sm outline-none transition-all
                           border-slate-200 focus:border-blue-400 focus:ring-2 focus:ring-blue-100
                           bg-slate-50 text-slate-800"
              />
            </div>

            {err && (
              <div className="px-4 py-3 rounded-lg bg-red-50 border border-red-200
                              text-red-700 text-sm font-medium">
                {err}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3.5 rounded-lg font-semibold text-sm tracking-wide
                         transition-colors duration-200 disabled:opacity-60
                         text-white"
              style={{ background: loading ? "#8a9bb0" : "#0a1628" }}
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10"
                            stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor"
                          d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                  Anmelden…
                </span>
              ) : "Anmelden →"}
            </button>
          </form>
        </div>

        {/* Footer note */}
        <p className="text-center text-xs mt-6 opacity-40 text-white">
          Kein Ersatz für professionelle Anlageberatung (Art. 3 lit. c FIDLEG)
        </p>
      </div>
    </div>
  );
}
