import type { ReactNode } from "react";

import { useApiKey } from "../context/apiKeyContext";
import { SettingsForm } from "./SettingsForm";

/** Gate: render children only when an API key is set; otherwise prompt for one. */
export function RequireApiKey({ children }: { children: ReactNode }) {
  const { hasKey } = useApiKey();
  if (hasKey) {
    return <>{children}</>;
  }

  return (
    <section className="mx-auto max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-900">API key required</h2>
      <p className="mt-1 mb-4 text-sm text-slate-600">
        Paste an API key to load data. Issue one with{" "}
        <code className="rounded bg-slate-100 px-1">make issue-api-key</code>.
      </p>
      <SettingsForm />
    </section>
  );
}
