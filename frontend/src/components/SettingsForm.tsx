import { useState, type FormEvent } from "react";

import { useApiKey } from "../context/apiKeyContext";

function maskKey(key: string): string {
  if (key.length <= 8) {
    return "••••";
  }
  return `${key.slice(0, 4)}…${key.slice(-4)}`;
}

/** Paste / save / clear the API key. Reused by the header panel and the gate. */
export function SettingsForm() {
  const { apiKey, hasKey, setKey, clearKey } = useApiKey();
  const [draft, setDraft] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setKey(draft);
    setDraft("");
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <label htmlFor="api-key-input" className="text-sm font-medium text-slate-700">
        API key
      </label>
      <input
        id="api-key-input"
        type="password"
        autoComplete="off"
        placeholder="qkf_…"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        className="rounded border border-slate-300 px-2 py-1 text-sm focus:border-slate-500 focus:outline-none"
      />
      <div className="flex gap-2">
        <button
          type="submit"
          className="rounded bg-slate-900 px-3 py-1 text-sm font-medium text-white hover:bg-slate-700"
        >
          Save
        </button>
        <button
          type="button"
          onClick={clearKey}
          disabled={!hasKey}
          className="rounded border border-slate-300 px-3 py-1 text-sm text-slate-700 hover:bg-slate-100 disabled:opacity-50"
        >
          Clear
        </button>
      </div>
      <p className="text-xs text-slate-500">
        {hasKey && apiKey ? `Current key: ${maskKey(apiKey)}` : "No key set."}
      </p>
    </form>
  );
}
