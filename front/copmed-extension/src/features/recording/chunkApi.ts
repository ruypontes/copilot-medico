import type { TranscriptionLogItem } from "../shared/types";
import { PermanentUploadError, UploadAuthError, type AudioChunk } from "./chunkUploader";

// Chamadas das rotas de áudio em partes (B30). Usado pelo documento offscreen, que não tem
// acesso ao chrome.storage: o token chega por `getToken` (pedido ao background.js a cada
// chamada, para que um novo login valha para os reenvios).

export type AudioApiConfig = {
  apiUrl: string;
  getToken: () => Promise<string | null>;
};

export type RecordingRef = {
  consultationId: string;
  recordingId: string;
};

export type TranscribeResponse = {
  transcription?: string;
  is_error?: boolean;
  used_fallback?: boolean;
  log_entry?: TranscriptionLogItem;
  chunks?: { received?: number[]; missing?: number[]; failed?: number[] };
};

// 408 e 429 são passageiros; os demais 4xx (400, 403, 404, 413...) não mudam com reenvio.
const isPermanent = (status: number) =>
  status >= 400 && status < 500 && status !== 408 && status !== 429;

export function createAudioApi({ apiUrl, getToken }: AudioApiConfig) {
  async function request(path: string, init: RequestInit): Promise<Response> {
    const token = await getToken();
    if (!token) throw new UploadAuthError();

    const response = await fetch(`${apiUrl}${path}`, {
      ...init,
      headers: { ...(init.headers as Record<string, string>), Authorization: `Bearer ${token}` },
    });
    if (response.status === 401) throw new UploadAuthError();
    if (!response.ok) {
      const message = `A API respondeu ${response.status}.`;
      throw isPermanent(response.status) ? new PermanentUploadError(message) : new Error(message);
    }
    return response;
  }

  const base = (consultationId: string) =>
    `/api/consultations/${encodeURIComponent(consultationId)}`;

  return {
    /** POST audio/chunks: envia (ou reenvia) uma parte com a sua sequência. */
    async sendChunk({ consultationId, recordingId }: RecordingRef, chunk: AudioChunk): Promise<void> {
      const form = new FormData();
      const name = `parte-${String(chunk.seq).padStart(4, "0")}.wav`;
      form.append("audio_file", new File([chunk.blob], name, { type: "audio/wav" }));
      form.append("recording_id", recordingId);
      form.append("seq", String(chunk.seq));
      await request(`${base(consultationId)}/audio/chunks`, { method: "POST", body: form });
    },

    /** POST transcribe: junta as partes recebidas e devolve a transcrição. */
    async transcribe(
      { consultationId, recordingId }: RecordingRef,
      totalChunks: number
    ): Promise<TranscribeResponse> {
      const response = await request(`${base(consultationId)}/transcribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recording_id: recordingId, total_chunks: totalChunks }),
      });
      return response.json();
    },
  };
}

/**
 * Repete `action` enquanto a falha for passageira (rede, 5xx, sessão expirada), até o prazo.
 * Usado na transcrição final: as partes já estão no servidor, vale insistir antes de desistir.
 */
export async function retryTransient<T>(
  action: () => Promise<T>,
  {
    deadlineMs,
    intervalMs,
    now = Date.now,
    wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)),
  }: { deadlineMs: number; intervalMs: number; now?: () => number; wait?: (ms: number) => Promise<void> }
): Promise<T> {
  const limit = now() + deadlineMs;
  for (;;) {
    try {
      return await action();
    } catch (error) {
      if (error instanceof PermanentUploadError || now() >= limit) throw error;
      await wait(intervalMs);
    }
  }
}
