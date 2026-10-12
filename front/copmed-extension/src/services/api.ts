export const API_URL = import.meta.env.VITE_API_URL || "http://localhost:3001";

const TOKEN_KEY = "copmed_extension_token";
const USER_KEY = "copmed_extension_user";
const PROFILE_KEY = "copmed_extension_profile";
const SESSION_KEYS = [TOKEN_KEY, USER_KEY, PROFILE_KEY];

// O background.js e um script puro (sem acesso ao import.meta.env do Vite): o popup
// publica aqui o API_URL efetivo e o background le deste mesmo lugar (B27).
export const API_URL_KEY = "copmed_api_url";

export type ExtensionSession = {
  token: string | null;
  user: Record<string, unknown> | null;
  profile: Record<string, unknown> | null;
};

type ApiRequestOptions = RequestInit & {
  token?: string | null;
  auth?: boolean;
};

/**
 * "session" = chrome.storage.session: fica so em memoria, e apagado ao fechar o navegador
 * ou recarregar a extensao e nao e exposto a content scripts. A sessao (token incluso)
 * mora la. "local" = persistente em disco: so preferencias que nao sao segredo.
 */
type StorageAreaName = "local" | "session";

function storageGet(area: StorageAreaName, keys: string[]): Promise<Record<string, unknown>> {
  return new Promise((resolve) => {
    chrome.storage[area].get(keys, (result) => resolve(result));
  });
}

function storageSet(area: StorageAreaName, values: Record<string, unknown>): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage[area].set(values, () => resolve());
  });
}

function storageRemove(area: StorageAreaName, keys: string[]): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage[area].remove(keys, () => resolve());
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

/**
 * Versoes anteriores guardavam o token em chrome.storage.local (em disco). Move-o para
 * a sessao, sem obrigar um novo login, e apaga a copia persistente. Idempotente.
 */
async function migrateLegacySession(): Promise<void> {
  const legacy = await storageGet("local", SESSION_KEYS);
  if (!SESSION_KEYS.some((key) => key in legacy)) return;

  const current = await storageGet("session", [TOKEN_KEY]);
  if (typeof legacy[TOKEN_KEY] === "string" && typeof current[TOKEN_KEY] !== "string") {
    await storageSet("session", legacy);
  }
  await storageRemove("local", SESSION_KEYS);
}

export async function getStoredSession(): Promise<ExtensionSession> {
  await migrateLegacySession();
  const stored = await storageGet("session", SESSION_KEYS);
  return {
    token: typeof stored[TOKEN_KEY] === "string" ? stored[TOKEN_KEY] : null,
    user: safeJsonParse(stored[USER_KEY]) as Record<string, unknown> | null,
    profile: safeJsonParse(stored[PROFILE_KEY]) as Record<string, unknown> | null,
  };
}

export async function storeSession(session: ExtensionSession): Promise<void> {
  await storageSet("session", {
    [TOKEN_KEY]: session.token,
    [USER_KEY]: JSON.stringify(session.user),
    [PROFILE_KEY]: JSON.stringify(session.profile),
  });
  // garante que nao sobra copia persistente de uma versao anterior
  await storageRemove("local", SESSION_KEYS);
}

export async function clearSession(): Promise<void> {
  await storageRemove("session", SESSION_KEYS);
  await storageRemove("local", SESSION_KEYS);
}

/** Publica o API_URL efetivo para o background.js (ver API_URL_KEY). */
export function publishApiUrl(): Promise<void> {
  return storageSet("local", { [API_URL_KEY]: API_URL });
}

async function parseJson(response: Response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { status: "error", message: text };
  }
}

export class SessionExpiredError extends Error {
  constructor() {
    super("Sessão expirada. Entre novamente.");
    this.name = "SessionExpiredError";
  }
}

/**
 * Renova a sessao quando a API responde 401. Recebe a sessao atual e devolve a nova
 * (ou null se nao foi possivel renovar). Ainda nao ha endpoint de refresh no backend
 * (entra com a B22): ate la nenhum renovador e registrado e todo 401 expira a sessao.
 */
export type SessionRefresher = (current: ExtensionSession) => Promise<ExtensionSession | null>;

let sessionRefresher: SessionRefresher | null = null;
let sessionExpiredHandler: (() => void) | null = null;
let refreshInFlight: Promise<ExtensionSession | null> | null = null;

export function setSessionRefresher(refresher: SessionRefresher | null) {
  sessionRefresher = refresher;
}

/** A UI registra aqui o que fazer quando a sessao expira (voltar para o login). */
export function setSessionExpiredHandler(handler: (() => void) | null) {
  sessionExpiredHandler = handler;
}

// Varias requisicoes podem receber 401 ao mesmo tempo: todas esperam a mesma renovacao.
function refreshSession(): Promise<ExtensionSession | null> {
  if (!sessionRefresher) return Promise.resolve(null);
  const refresher = sessionRefresher;
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const current = await getStoredSession();
        if (!current.token) return null;
        const next = await refresher(current);
        if (!next?.token) return null;
        await storeSession(next);
        return next;
      } catch {
        return null;
      }
    })().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function sendRequest(
  path: string,
  authToken: string | null | undefined,
  customHeaders: Record<string, string> | undefined,
  options: RequestInit
) {
  const isFormData = options.body instanceof FormData;
  return fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...customHeaders,
    },
  });
}

export async function apiRequest(path: string, { token, auth = true, headers, ...options }: ApiRequestOptions = {}) {
  // So requisicoes que usam a sessao guardada disparam o tratamento de 401. Um 401 no login
  // (auth: false) e "senha errada", nao sessao expirada.
  const usesStoredSession = auth && token === undefined;
  const session = usesStoredSession ? await getStoredSession() : null;
  const authToken = token === undefined ? session?.token : token;
  const customHeaders = headers as Record<string, string> | undefined;

  let response = await sendRequest(path, auth ? authToken : null, customHeaders, options);

  if (response.status === 401 && usesStoredSession) {
    const refreshed = await refreshSession();
    if (refreshed?.token) {
      response = await sendRequest(path, refreshed.token, customHeaders, options);
    }
    if (response.status === 401) {
      await clearSession();
      sessionExpiredHandler?.();
      throw new SessionExpiredError();
    }
  }

  const data = await parseJson(response);
  if (!response.ok) {
    const message = data.message || data.error || "Erro na comunicação com a API.";
    throw new Error(message);
  }
  return data;
}

export function login(payload: { email: string; password: string; profile: string }) {
  return apiRequest("/api/auth/login", {
    auth: false,
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAuthenticatedUser() {
  return apiRequest("/api/auth/me");
}

export function getPatients() {
  return apiRequest("/api/all-patients");
}

export function createPatient(payload: { name: string }) {
  return apiRequest("/api/patients", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getPatientConsultations(patientId: string) {
  return apiRequest(`/api/patients/${encodeURIComponent(patientId)}/consultations`);
}

export function createConsultation(patientId: string, payload: Record<string, unknown>) {
  return apiRequest(`/api/patients/${encodeURIComponent(patientId)}/consultations`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getConsultationHistory(patientId: string, consultationId: string) {
  return apiRequest(
    `/api/patients/${encodeURIComponent(patientId)}/consultations/${encodeURIComponent(consultationId)}/history`
  );
}

export function sendChatMessage(payload: Record<string, unknown>) {
  return apiRequest("/api/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function uploadPdf(formData: FormData) {
  return apiRequest("/api/upload-pdf", {
    method: "POST",
    body: formData,
  });
}

export function sendExtractedData(payload: Record<string, unknown>) {
  return apiRequest("/api/extension/extracted-data", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getTranscriptionLog(patientId: string) {
  return apiRequest(`/api/patients/${encodeURIComponent(patientId)}/transcription-log`);
}
