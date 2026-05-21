import { useState } from "react";

import { useApiKey } from "../context/apiKeyContext";
import { SettingsForm } from "./SettingsForm";

/** Header disclosure that toggles the API-key form. */
export function SettingsPanel() {
  const { hasKey } = useApiKey();
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="rounded border border-slate-300 px-3 py-1 text-sm text-slate-700 hover:bg-slate-100"
      >
        {hasKey ? "API key ✓" : "Set API key"}
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-2 w-72 rounded-lg border border-slate-200 bg-white p-4 shadow-lg">
          <SettingsForm />
        </div>
      )}
    </div>
  );
}
