import { render, type RenderOptions } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement, ReactNode } from "react";
import { SWRConfig } from "swr";
import { seedAuth, type Role } from "./auth";

export interface RenderWithProvidersOptions extends Omit<RenderOptions, "wrapper"> {
  /** Bila diisi, store auth di-seed dengan peran ini sebelum render. */
  role?: Role;
}

/**
 * Render dengan provider aplikasi untuk test:
 * - SWRConfig dengan cache BARU per render (tanpa kebocoran antar test), tanpa dedupe, tanpa retry;
 * - (opsional) seeding auth per peran.
 * Aplikasi nyata tidak memasang SWRConfig; ini hanya isolasi test.
 * Mengembalikan `user` (user-event) siap pakai.
 */
export function renderWithProviders(ui: ReactElement, options: RenderWithProvidersOptions = {}) {
  const { role, ...renderOptions } = options;
  if (role) seedAuth(role);

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <SWRConfig
        value={{
          provider: () => new Map(),
          dedupingInterval: 0,
          errorRetryCount: 0,
          shouldRetryOnError: false,
        }}
      >
        {children}
      </SWRConfig>
    );
  }

  return { user: userEvent.setup(), ...render(ui, { wrapper: Wrapper, ...renderOptions }) };
}
