import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { SessionProvider, useSession } from "./SessionContext";
import { Header } from "./Header";
import { ChatRoute } from "./routes/ChatRoute";
import { NotificationsRoute } from "./routes/NotificationsRoute";
import { fetchManifest, RemoteManifest } from "./utils/manifest";

function LoginGate({ children }: { children: React.ReactNode }) {
  const { session, setUserId } = useSession();
  const [input, setInput] = React.useState("");

  if (session) return <>{children}</>;

  return (
    <div style={{ padding: 40, maxWidth: 420 }}>
      <h1>EduMind</h1>
      <p>No real login yet — enter a known user id (the backend's auth is a bare X-User-Id header).</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (input.trim()) setUserId(input.trim());
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="user id (uuid)"
          style={{ width: "100%", padding: 8, marginBottom: 8 }}
        />
        <button type="submit">Continue</button>
      </form>
    </div>
  );
}

function AuthedApp() {
  const { session } = useSession();
  const [manifest, setManifest] = React.useState<RemoteManifest | null>(null);
  const [manifestError, setManifestError] = React.useState<string | null>(null);

  React.useEffect(() => {
    fetchManifest()
      .then(setManifest)
      .catch((err) => setManifestError(String(err)));
  }, []);

  if (manifestError) return <div style={{ padding: 40 }}>Failed to load remotes.json: {manifestError}</div>;
  if (!manifest) return <div style={{ padding: 40 }}>Loading…</div>;
  if (!session) return null; // LoginGate above guarantees this never renders

  return (
    <>
      <Header manifest={manifest} session={session} />
      <main style={{ padding: 20 }}>
        <Routes>
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route path="/chat/*" element={<ChatRoute manifest={manifest} session={session} />} />
          <Route path="/notifications" element={<NotificationsRoute manifest={manifest} session={session} />} />
        </Routes>
      </main>
    </>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <SessionProvider>
        <LoginGate>
          <AuthedApp />
        </LoginGate>
      </SessionProvider>
    </BrowserRouter>
  );
}
