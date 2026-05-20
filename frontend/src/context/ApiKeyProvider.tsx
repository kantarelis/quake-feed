import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { clearApiKey, getApiKey, setApiKey, subscribeApiKey } from "../api/keyStore";
import { ApiKeyContext, type ApiKeyContextValue } from "./apiKeyContext";

export function ApiKeyProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKeyState] = useState<string | null>(() => getApiKey());

  useEffect(() => {
    // Re-sync after mount and on every store change (incl. cross-tab edits).
    const unsubscribe = subscribeApiKey(setApiKeyState);
    setApiKeyState(getApiKey());
    return unsubscribe;
  }, []);

  const setKey = useCallback((key: string) => {
    setApiKey(key);
  }, []);
  const clearKey = useCallback(() => {
    clearApiKey();
  }, []);

  const value = useMemo<ApiKeyContextValue>(
    () => ({ apiKey, hasKey: apiKey !== null, setKey, clearKey }),
    [apiKey, setKey, clearKey],
  );

  return <ApiKeyContext.Provider value={value}>{children}</ApiKeyContext.Provider>;
}
