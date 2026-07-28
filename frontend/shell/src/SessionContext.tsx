import React from "react";

// Matches the backend's actual auth model: a bare X-User-Id header, no real
// login/JWT anywhere in the system. Structured as its own context (rather
// than inline state in App.tsx) so a future "auth remote" can slot in later
// without a rewrite — out of scope for this pass.
export interface Session {
  userId: string;
}

const STORAGE_KEY = "edumind.userId";

const SessionContext = React.createContext<{
  session: Session | null;
  setUserId: (userId: string) => void;
  clearSession: () => void;
} | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [userId, setUserIdState] = React.useState<string | null>(() =>
    localStorage.getItem(STORAGE_KEY)
  );

  const setUserId = React.useCallback((id: string) => {
    localStorage.setItem(STORAGE_KEY, id);
    setUserIdState(id);
  }, []);

  const clearSession = React.useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setUserIdState(null);
  }, []);

  const value = React.useMemo(
    () => ({
      session: userId ? { userId } : null,
      setUserId,
      clearSession,
    }),
    [userId, setUserId, clearSession]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = React.useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within a SessionProvider");
  return ctx;
}
