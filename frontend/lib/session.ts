"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { TenantOut, TokenResponse, UserOut } from "@/lib/types";

export interface SessionState {
  token: string | null;
  user: UserOut | null;
  tenant: TenantOut | null;
  expiresAt: number | null;
  hydrated: boolean;
  setSession: (response: TokenResponse) => void;
  updateTenant: (tenant: TenantOut) => void;
  updateUser: (user: UserOut) => void;
  clear: () => void;
  setHydrated: () => void;
}

export const SESSION_STORAGE_KEY = "opspilot.session.v1";

export const useSession = create<SessionState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      tenant: null,
      expiresAt: null,
      hydrated: false,
      setSession: (response) =>
        set({
          token: response.access_token,
          user: response.user,
          tenant: response.tenant,
          expiresAt: Date.now() + response.expires_in * 1000,
        }),
      updateTenant: (tenant) => set({ tenant }),
      updateUser: (user) => set({ user }),
      clear: () => set({ token: null, user: null, tenant: null, expiresAt: null }),
      setHydrated: () => set({ hydrated: true }),
    }),
    {
      name: SESSION_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ token: state.token, user: state.user, tenant: state.tenant, expiresAt: state.expiresAt }),
      skipHydration: true,
    },
  ),
);

/** True when the stored session has a token that has not expired. */
export function isSessionValid(state: Pick<SessionState, "token" | "expiresAt">): boolean {
  if (!state.token) return false;
  if (state.expiresAt && state.expiresAt <= Date.now()) return false;
  return true;
}
