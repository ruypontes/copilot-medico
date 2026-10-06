// Sessão da extensão: token em chrome.storage.session (apagado ao fechar o navegador),
// renovação pelo refresh token e aviso central quando a sessão expira.

export const API_URL = import.meta.env.VITE_API_URL || "http://localhost:3001";

const TOKEN_KEY = "copmed_extension_token";
const REFRESH_KEY = "copmed_extension_refresh_token";
const EXPIRES_KEY = "copmed_extension_expires_at";
const USER_KEY = "copmed_extension_user";
const PROFILE_KEY = "copmed_extension_profile";
const SESSION_KEYS = [TOKEN_KEY, REFRESH_KEY, EXPIRES_KEY, USER_KEY, PROFILE_KEY];
// O background.js lê a URL da API daqui (ele não passa pelo Vite).
const API_URL_KEY = "copmed_api_url";
// Renova o token quando faltar menos que isso para expirar.
const RENEW_MARGIN_MS = 60_000;

export const SESSION_EXPIRED_MESSAGE = "Sessão expirada. Entre novamente.";

export type ExtensionSession = {
  token: string | null;
  user: Record<string, unknown> | null;
  profile: Record<string, unknown> | null;
  refreshToken?: string | null;
  expiresAt?: number | null;
};

type StorageArea = chrome.storage.StorageArea;

function sessionArea(): StorageArea {
  return chrome.storage.session ?? chrome.storage.local;
}

function storageGet(area: StorageArea, keys: string[]): Promise<Record<string, unknown>> {
  return new Promise((resolve) => {
    area.get(keys, (result) => resolve(result || {}));
  });
}

function storageSet(area: StorageArea, values: Record<string, unknown>): Promise<void> {
  return new Promise((resolve) => {
    area.set(values, () => resolve());
  });
}

function storageRemove(area: StorageArea, keys: string[]): Promise<void> {
  return new Promise((resolve) => {
    area.remove(keys, () => resolve());
  });
}

function safeJsonParse(value: unknown) {
  if (typeof value !== "string") return value || null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function asString(value: unknown) {
  return typeof value === "string" && value ? value : null;
}

// Sessões salvas por versões antigas ficavam no chrome.storage.local; passam para o session.
async function migrateLegacySession() {
  if (sessionArea() === chrome.storage.local) return;
  const legacy = await storageGet(chrome.storage.local, SESSION_KEYS);
  if (!legacy[TOKEN_KEY]) return;
  await storageSet(sessionArea(), legacy);
  await storageRemove(chrome.storage.local, SESSION_KEYS);
}

export async function getStoredSession(): Promise<ExtensionSession> {
  await migrateLegacySession();
  const stored = await storageGet(sessionArea(), SESSION_KEYS);
  const expiresAt = Number(stored[EXPIRES_KEY]);
  return {
    token: asString(stored[TOKEN_KEY]),
    refreshToken: asString(stored[REFRESH_KEY]),
    expiresAt: Number.isFinite(expiresAt) && expiresAt > 0 ? expiresAt : null,
    user: safeJsonParse(stored[USER_KEY]) as Record<string, unknown> | null,
    profile: safeJsonParse(stored[PROFILE_KEY]) as Record<string, unknown> | null,
  };
}

export async function storeSession(session: ExtensionSession): Promise<void> {
  const values: Record<string, unknown> = {
    [TOKEN_KEY]: session.token,
    [USER_KEY]: JSON.stringify(session.user),
    [PROFILE_KEY]: JSON.stringify(session.profile),
  };
  if (session.refreshToken !== undefined) values[REFRESH_KEY] = session.refreshToken;
  if (session.expiresAt !== undefined) values[EXPIRES_KEY] = session.expiresAt;
  await storageSet(sessionArea(), values);
  await storageSet(chrome.storage.local, { [API_URL_KEY]: API_URL });
}

export async function clearSession(): Promise<void> {
  await storageRemove(sessionArea(), SESSION_KEYS);
  await storageRemove(chrome.storage.local, SESSION_KEYS);
}

// Monta a sessão a partir da resposta de /api/auth/login, /select-profile ou /refresh.
export function sessionFromAuthResponse(
  data: Record<string, unknown>,
  previous?: ExtensionSession | null
): ExtensionSession {
  const expiresIn = Number(data.expires_in);
  return {
    token: asString(data.token) ?? asString(data.access_token),
    refreshToken: asString(data.refresh_token) ?? previous?.refreshToken ?? null,
    expiresAt: Number.isFinite(expiresIn) && expiresIn > 0 ? Date.now() + expiresIn * 1000 : null,
    user: (data.user as Record<string, unknown>) ?? previous?.user ?? null,
    profile: (data.profile as Record<string, unknown>) ?? previous?.profile ?? null,
  };
}

const expiredListeners = new Set<() => void>();

// O App se inscreve aqui para voltar ao login quando a sessão não puder ser renovada.
export function onSessionExpired(listener: () => void) {
  expiredListeners.add(listener);
  return () => {
    expiredListeners.delete(listener);
  };
}

export async function expireSession() {
  await clearSession();
  expiredListeners.forEach((listener) => listener());
}

let refreshing: Promise<ExtensionSession | null> | null = null;

async function requestRefresh(): Promise<ExtensionSession | null> {
  const current = await getStoredSession();
  if (!current.refreshToken) return null;
  try {
    const response = await fetch(`${API_URL}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: current.refreshToken }),
    });
    if (!response.ok) return null;
    const next = sessionFromAuthResponse(JSON.parse((await response.text()) || "{}"), current);
    if (!next.token) return null;
    await storeSession(next);
    return next;
  } catch {
    return null;
  }
}

// Várias chamadas podem receber 401 ao mesmo tempo; todas esperam a mesma renovação.
export function refreshSession(): Promise<ExtensionSession | null> {
  if (!refreshing) {
    refreshing = requestRefresh().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

// Token pronto para uso: renova antes de vencer quando há refresh token.
export async function getValidToken(): Promise<string | null> {
  const session = await getStoredSession();
  if (session.token && session.refreshToken && session.expiresAt && session.expiresAt - Date.now() < RENEW_MARGIN_MS) {
    const renewed = await refreshSession();
    if (renewed?.token) return renewed.token;
  }
  return session.token;
}
