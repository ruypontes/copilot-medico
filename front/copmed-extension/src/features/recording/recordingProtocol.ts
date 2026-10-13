import type { TranscriptionLogItem } from "../shared/types";

// Contrato da gravação entre o popup, o background.js e o documento offscreen (B29/B30).
//
// Quem grava é o documento offscreen: o popup é destruído ao fechar e levaria o MediaRecorder
// junto. O offscreen publica o estado, o background.js o guarda em chrome.storage.session e o
// popup só lê esse estado e envia comandos — por isso a gravação sobrevive ao fechar o popup.
// As chaves e os tipos de mensagem daqui são repetidos em public/background.js (script puro).

/** Onde o background.js guarda o RecordingSnapshot (chrome.storage.session: só em memória). */
export const RECORDING_STATE_KEY = "copmed_recording_state";

/**
 * Só para testes manuais: permite ENCURTAR (nunca aumentar) um prazo por variável do Vite,
 * para não esperar 5 e 120 minutos de gravação. Ex., em front/copmed-extension/.env.local:
 *   VITE_RECORDING_CHUNK_SECONDS=20
 *   VITE_RECORDING_MAX_SECONDS=90
 */
export function shortenedBy(seconds: unknown, defaultMs: number): number {
  const value = Number(seconds);
  return Number.isFinite(value) && value > 0 ? Math.min(defaultMs, value * 1000) : defaultMs;
}

/** US017-CA002: a gravação para sozinha ao atingir 120 min. */
export const MAX_RECORDING_MS = shortenedBy(
  import.meta.env.VITE_RECORDING_MAX_SECONDS,
  120 * 60 * 1000
);
/** US017-CA003: o áudio segue para o backend em partes de até 5 min. */
export const CHUNK_MAX_MS = 5 * 60 * 1000;
// A troca de parte é conferida a cada ~1 s; a folga garante que nenhuma parte passe de 5 min.
export const CHUNK_ROTATION_MS = shortenedBy(
  import.meta.env.VITE_RECORDING_CHUNK_SECONDS,
  CHUNK_MAX_MS - 5000
);

export type RecordingStatus = "idle" | "recording" | "paused" | "finalizing";

/** manual = botão Parar; limit = 120 min; device = o microfone foi desconectado. */
export type StopReason = "manual" | "limit" | "device";

/** Resultado de uma gravação encerrada, guardado até o popup entregá-lo ao chat. */
export type RecordingResult = {
  recordingId: string;
  patientId: string;
  consultationId: string;
  stopReason: StopReason;
  transcription: string | null;
  logEntry: TranscriptionLogItem | null;
  /** Mensagem para o médico quando não houve transcrição. */
  error: string | null;
  /** Partes que não chegaram ao servidor ou não puderam ser transcritas. */
  missingChunks: number[];
};

export type RecordingSnapshot = {
  status: RecordingStatus;
  recordingId: string | null;
  patientId: string | null;
  consultationId: string | null;
  /** Tempo gravado até a última pausa. */
  accumulatedMs: number;
  /** Início do trecho em curso (epoch ms); null quando pausado ou parado. */
  resumedAt: number | null;
  chunksSent: number;
  chunksPending: number;
  /** Partes que o servidor recusou de vez (ex.: consulta inexistente ou sem acesso). */
  chunksRejected: number;
  /** Por que há partes aguardando reenvio. */
  warning: "session_expired" | "upload_failed" | null;
  result: RecordingResult | null;
};

export const IDLE_SNAPSHOT: RecordingSnapshot = {
  status: "idle",
  recordingId: null,
  patientId: null,
  consultationId: null,
  accumulatedMs: 0,
  resumedAt: null,
  chunksSent: 0,
  chunksPending: 0,
  chunksRejected: 0,
  warning: null,
  result: null,
};

/** Comandos do popup para o background.js. */
export type RecordingCommand =
  | { type: "recording:start"; patientId: string; consultationId: string }
  | { type: "recording:pause" }
  | { type: "recording:resume" }
  | { type: "recording:stop" }
  | { type: "recording:cancel" }
  | { type: "recording:sync" }
  | { type: "recording:ack-result" };

export type RecordingReply = {
  ok: boolean;
  error?: string;
  snapshot?: RecordingSnapshot;
};

/**
 * Tempo gravado (sem as pausas). O cronômetro é sempre calculado a partir do estado, nunca
 * incrementado: assim continua certo quando o popup reabre no meio da gravação.
 */
export function elapsedMs(
  snapshot: Pick<RecordingSnapshot, "accumulatedMs" | "resumedAt">,
  now: number
): number {
  const running = snapshot.resumedAt === null ? 0 : Math.max(0, now - snapshot.resumedAt);
  return Math.min(MAX_RECORDING_MS, snapshot.accumulatedMs + running);
}

/** Estado lido do storage: qualquer coisa fora do formato vira "sem gravação". */
export function normalizeSnapshot(value: unknown): RecordingSnapshot {
  if (!value || typeof value !== "object") return IDLE_SNAPSHOT;
  const stored = value as Partial<RecordingSnapshot>;
  if (!["idle", "recording", "paused", "finalizing"].includes(String(stored.status))) {
    return IDLE_SNAPSHOT;
  }
  return { ...IDLE_SNAPSHOT, ...stored };
}
