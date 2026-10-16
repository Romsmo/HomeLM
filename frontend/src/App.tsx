import { useCallback, useEffect, useState } from "react";
import { fetchMe, logout } from "./api";
import Dashboard from "./components/Dashboard";
import Login from "./components/Login";

type AuthState = "checking" | "anonymous" | "authenticated";

export default function App() {
  const [auth, setAuth] = useState<AuthState>("checking");

  useEffect(() => {
    let cancelled = false;
    void fetchMe().then((check) => {
      if (!cancelled) setAuth(check === "authenticated" ? "authenticated" : "anonymous");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Der WebSocket kam nicht zustande. Nur bei klarem 401 (Sitzung abgelaufen) zur Anmeldung;
  // ist der Server bloß kurz weg, bleibt das Dashboard und die Wiederverbindung läuft weiter.
  const recheck = useCallback(() => {
    void fetchMe().then((check) => {
      if (check === "anonymous") setAuth("anonymous");
    });
  }, []);

  const doLogout = useCallback(() => {
    void logout().then(() => setAuth("anonymous"));
  }, []);

  if (auth === "checking") {
    return <main className="min-h-dvh" aria-busy="true" aria-label="Cat" />;
  }
  if (auth === "anonymous") {
    return <Login onSuccess={() => setAuth("authenticated")} />;
  }
  return <Dashboard onUnreachable={recheck} onLogout={doLogout} />;
}
