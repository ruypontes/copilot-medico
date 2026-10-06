export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:3001';

const TOKEN_KEY = 'copmed_web_token';
const REFRESH_KEY = 'copmed_web_refresh_token';
const EXPIRES_KEY = 'copmed_web_expires_at';
const USER_KEY = 'copmed_web_user';
const PROFILE_KEY = 'copmed_web_profile';
// Renova o token quando faltar menos que isso para expirar.
const RENEW_MARGIN_MS = 60_000;

export const SESSION_EXPIRED_MESSAGE = 'Sessão expirada. Entre novamente.';

export function getStoredSession() {
  const token = localStorage.getItem(TOKEN_KEY);
  const rawUser = localStorage.getItem(USER_KEY);
  const rawProfile = localStorage.getItem(PROFILE_KEY);

  let user = null;
  let profile = null;
  try {
    user = rawUser ? JSON.parse(rawUser) : null;
    profile = rawProfile ? JSON.parse(rawProfile) : null;
  } catch {
    clearSession();
  }

  const expiresAt = Number(localStorage.getItem(EXPIRES_KEY));
  return {
    token,
    user,
    profile,
    refreshToken: localStorage.getItem(REFRESH_KEY),
    expiresAt: expiresAt > 0 ? expiresAt : null,
  };
}

export function storeSession({ token, user, profile, refreshToken, expiresAt }) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
  if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken);
  else localStorage.removeItem(REFRESH_KEY);
  if (expiresAt) localStorage.setItem(EXPIRES_KEY, String(expiresAt));
  else localStorage.removeItem(EXPIRES_KEY);
}

export function clearSession() {
  [TOKEN_KEY, REFRESH_KEY, EXPIRES_KEY, USER_KEY, PROFILE_KEY].forEach((key) => localStorage.removeItem(key));
}

// Monta a sessão a partir da resposta de /api/auth/login ou /api/auth/refresh.
export function sessionFromAuthResponse(data, previous = null) {
  const expiresIn = Number(data.expires_in);
  return {
    token: data.token || data.access_token || null,
    refreshToken: data.refresh_token || previous?.refreshToken || null,
    expiresAt: expiresIn > 0 ? Date.now() + expiresIn * 1000 : null,
    user: data.user || previous?.user || null,
    profile: data.profile || previous?.profile || null,
  };
}

// O App se inscreve para receber o token renovado ou voltar ao login quando a sessão expira.
const sessionListeners = new Set();

export function onSessionChange(listener) {
  sessionListeners.add(listener);
  return () => sessionListeners.delete(listener);
}

function notifySession(session) {
  sessionListeners.forEach((listener) => listener(session));
}

let refreshing = null;

async function requestRefresh() {
  const current = getStoredSession();
  if (!current.refreshToken) return null;
  try {
    const response = await fetch(`${API_URL}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: current.refreshToken }),
    });
    if (!response.ok) return null;
    const next = sessionFromAuthResponse(await parseJson(response), current);
    if (!next.token) return null;
    storeSession(next);
    notifySession(next);
    return next;
  } catch {
    return null;
  }
}

// Várias chamadas podem receber 401 ao mesmo tempo; todas esperam a mesma renovação.
function refreshSession() {
  if (!refreshing) {
    refreshing = requestRefresh().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

// Renova antes de vencer quando o token é o da sessão salva e há refresh token.
async function getValidToken(token) {
  const stored = getStoredSession();
  if (token !== stored.token || !stored.refreshToken || !stored.expiresAt) return token;
  if (stored.expiresAt - Date.now() >= RENEW_MARGIN_MS) return token;
  const renewed = await refreshSession();
  return renewed?.token || token;
}

function expireSession() {
  clearSession();
  notifySession(null);
}

async function parseJson(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { status: 'error', message: text };
  }
}

function send(path, options, headers, token) {
  return fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  });
}

// Tratamento central de 401: renova o token uma vez e repete a chamada;
// sem renovação possível, apaga a sessão e avisa o App para voltar ao login.
export async function apiRequest(path, { token, headers, ...options } = {}) {
  const authToken = token ? await getValidToken(token) : token;
  let response = await send(path, options, headers, authToken);

  if (response.status === 401 && authToken) {
    const renewed = await refreshSession();
    if (renewed?.token) {
      response = await send(path, options, headers, renewed.token);
    }
    if (response.status === 401) {
      expireSession();
      throw new Error(SESSION_EXPIRED_MESSAGE);
    }
  }

  const data = await parseJson(response);
  if (!response.ok) {
    const message = data.message || data.error || 'Erro na comunicação com a API.';
    throw new Error(message);
  }
  return data;
}

export function login({ email, password, profile }) {
  return apiRequest('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password, profile }),
  });
}

export function registerDoctor(payload) {
  return apiRequest('/api/auth/register-doctor', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getDoctorRequests(token, status = 'pending') {
  const query = status ? `?status=${encodeURIComponent(status)}` : '';
  return apiRequest(`/api/admin/doctor-requests${query}`, { token });
}

export function approveDoctor(token, userId) {
  return apiRequest(`/api/admin/doctor-requests/${encodeURIComponent(userId)}/approve`, {
    token,
    method: 'PATCH',
  });
}

export function rejectDoctor(token, userId, reason) {
  return apiRequest(`/api/admin/doctor-requests/${encodeURIComponent(userId)}/reject`, {
    token,
    method: 'PATCH',
    body: JSON.stringify({ reason }),
  });
}

export function getPatients(token) {
  return apiRequest('/api/all-patients', { token });
}

export function createPatient(token, payload) {
  return apiRequest('/api/patients', {
    token,
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getPatientConsultations(token, patientId) {
  return apiRequest(`/api/patients/${encodeURIComponent(patientId)}/consultations`, { token });
}

export function getPatientExtensionData(token, patientId) {
  return apiRequest(`/api/patients/${encodeURIComponent(patientId)}/extension-data`, { token });
}
