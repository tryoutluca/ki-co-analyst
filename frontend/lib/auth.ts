"use client";

import { useSyncExternalStore } from "react";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

export function getUsername(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("username") ?? "";
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

export function logout() {
  localStorage.removeItem("token");
  localStorage.removeItem("username");
}

// localStorage als externer Store: kein setState im Effect, SSR liefert "".
const subscribe = (cb: () => void) => {
  window.addEventListener("storage", cb);
  return () => window.removeEventListener("storage", cb);
};

export function useUsername(): string {
  return useSyncExternalStore(subscribe, getUsername, () => "");
}
