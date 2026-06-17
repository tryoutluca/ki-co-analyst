import axios from "axios";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const api = axios.create({ baseURL: BASE });

// Token aus localStorage an jeden Request anhängen
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// 401 → ausloggen (aber nicht beim Login/Register selbst)
api.interceptors.response.use(
  (r) => r,
  (err) => {
    const url: string = err.config?.url ?? "";
    const isAuthEndpoint = url.includes("/auth/login") || url.includes("/auth/register");
    if (err.response?.status === 401 && !isAuthEndpoint) {
      localStorage.removeItem("token");
      localStorage.removeItem("username");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

// ── Auth ─────────────────────────────────────────────────────────────────────

export async function login(username: string, password: string) {
  const form = new URLSearchParams({ username, password });
  const { data } = await api.post("/auth/login", form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  localStorage.setItem("token", data.access_token);
  localStorage.setItem("username", data.username);
  return data;
}

export async function changePassword(old_password: string, new_password: string) {
  return api.put("/auth/password", { old_password, new_password });
}

export async function register(email: string, username: string, password: string) {
  const { data } = await api.post("/auth/register", { email, username, password });
  return data;
}

// ── Search ───────────────────────────────────────────────────────────────────

export async function searchTicker(q: string) {
  const { data } = await api.get<{ ticker: string; display: string }[]>("/search", {
    params: { q },
  });
  return data;
}

// ── Analysis ─────────────────────────────────────────────────────────────────

export async function startAnalysis(ticker: string): Promise<{ job_id: string }> {
  const { data } = await api.post(`/analyse/${ticker}`);
  return data;
}

export async function getJobStatus(jobId: string, after = 0) {
  const { data } = await api.get(`/analyse/jobs/${jobId}`, { params: { after } });
  return data as {
    job_id: string;
    status: "running" | "done" | "error";
    ticker: string;
    progress: string[];
    result: Record<string, unknown> | null;
    error: string | null;
    hist_id: string | null;
  };
}

// ── History ──────────────────────────────────────────────────────────────────

export async function getHistory(limit = 50) {
  const { data } = await api.get("/history", { params: { limit } });
  return data as HistoryItem[];
}

export async function getHistoryItem(id: string) {
  const { data } = await api.get(`/history/${id}`);
  return data as Record<string, unknown>;
}

export async function deleteHistoryItem(id: string) {
  return api.delete(`/history/${id}`);
}

export async function downloadMemoPdf(histId: string, filename: string) {
  const token = localStorage.getItem("token") ?? "";
  const base  = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const res   = await fetch(`${base}/history/${histId}/pdf`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`PDF-Fehler: ${res.status}`);
  const blob = await res.blob();
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function getHistoryStats() {
  const { data } = await api.get("/history/stats/summary");
  return data as { total: number; last: HistoryItem | null; by_rec: Record<string, number> };
}

// ── Types ────────────────────────────────────────────────────────────────────

export interface HistoryItem {
  id: string;
  ticker: string;
  company: string;
  date: string;
  recommendation: string;
  price_target: string | number;
  upside: number | null;
  conviction: string;
  score: number | null;
  currency: string;
}
