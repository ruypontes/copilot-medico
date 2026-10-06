import { useState, useEffect } from "react";
import "./App.css";
import {
  clearSession,
  getAuthenticatedUser,
  getStoredSession,
  onSessionExpired,
  storeSession,
  type ExtensionSession,
} from "./services/api";
import ExtensionLogin from "./features/auth/ExtensionLogin";
import AuthenticatedApp from "./features/consultation/AuthenticatedApp";
import AppHeader from "./features/shared/AppHeader";

// Roteador de sessão: valida o token salvo e decide entre login e app autenticado.
function App() {
  const [session, setSession] = useState<ExtensionSession | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    let ignore = false;

    async function validateStoredSession() {
      try {
        const storedSession = await getStoredSession();
        if (!storedSession.token) {
          if (!ignore) {
            setSession(null);
            setAuthChecked(true);
          }
          return;
        }

        const data = await getAuthenticatedUser();
        // Relê a sessão: o token pode ter sido renovado durante a chamada.
        const currentSession = await getStoredSession();
        const nextSession = {
          ...currentSession,
          user: data.user || currentSession.user,
          profile: data.profile || currentSession.profile,
        };
        await storeSession(nextSession);
        if (!ignore) {
          setSession(nextSession);
          setAuthChecked(true);
        }
      } catch {
        await clearSession();
        if (!ignore) {
          setSession(null);
          setAuthError("Sessão expirada. Entre novamente.");
          setAuthChecked(true);
        }
      }
    }

    validateStoredSession();
    return () => {
      ignore = true;
    };
  }, []);

  // Qualquer chamada que receba 401 sem conseguir renovar o token volta para o login.
  useEffect(
    () =>
      onSessionExpired(() => {
        setSession(null);
        setAuthError("Sessão expirada. Entre novamente.");
      }),
    []
  );

  async function handleLoginSuccess(nextSession: ExtensionSession) {
    await storeSession(nextSession);
    setAuthError("");
    setSession(nextSession);
  }

  async function handleLogout() {
    await clearSession();
    chrome.storage.local.remove(["patientId", "patientName", "consultationId", "consultationTitle"]);
    setSession(null);
  }

  if (!authChecked) {
    return (
      <div className="App">
        <AppHeader />
        <div style={{ padding: "20px", textAlign: "center" }}>Validando sessão...</div>
      </div>
    );
  }

  if (!session?.token) {
    return <ExtensionLogin error={authError} onLoginSuccess={handleLoginSuccess} />;
  }

  return <AuthenticatedApp onLogout={handleLogout} />;
}

export default App;
