import { createContext, useContext } from "react";

export interface ApiKeyContextValue {
  /** The current API key, or null when none is configured. */
  apiKey: string | null;
  hasKey: boolean;
  setKey: (key: string) => void;
  clearKey: () => void;
}

// Split from the provider component so this file exports no components — keeps
// React Fast Refresh happy (a file mixing components + hooks/consts warns).
export const ApiKeyContext = createContext<ApiKeyContextValue | null>(null);

export function useApiKey(): ApiKeyContextValue {
  const context = useContext(ApiKeyContext);
  if (!context) {
    throw new Error("useApiKey must be used within an ApiKeyProvider");
  }
  return context;
}
