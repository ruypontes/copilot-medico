import {
  API_URL,
  SESSION_EXPIRED_MESSAGE,
  expireSession,
  getValidToken,
  refreshSession,
} from "./session";

export {
  API_URL,
  clearSession,
  getStoredSession,
  onSessionExpired,
  sessionFromAuthResponse,
  storeSession,
  type ExtensionSession,
} from "./session";

type ApiRequestOptions = RequestInit & {
  token?: string | null;
  auth?: boolean;
};

async function parseJson(response: Response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { status: "error", message: text };
  }
}

function send(path: string, options: RequestInit, headers: HeadersInit | undefined, authToken: string | null) {
  const isFormData = options.body instanceof FormData;
  return fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...(headers as Record<string, string> | undefined),
    },
  });
}

// Tratamento central de 401: renova o token uma vez e repete a chamada;
// sem renovação possível, apaga a sessão e avisa o App para voltar ao login.
export async function apiRequest(path: string, { token, auth = true, headers, ...options }: ApiRequestOptions = {}) {
  const usesStoredToken = auth && token === undefined;
  const authToken = !auth ? null : usesStoredToken ? await getValidToken() : token ?? null;

  let response = await send(path, options, headers, authToken);

  if (response.status === 401 && usesStoredToken && authToken) {
    const renewed = await refreshSession();
    if (renewed?.token) {
      response = await send(path, options, headers, renewed.token);
    }
    if (response.status === 401) {
      await expireSession();
      throw new Error(SESSION_EXPIRED_MESSAGE);
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

export function sendAudio(formData: FormData) {
  return apiRequest("/api/transcribe_audio", {
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
