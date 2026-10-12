import { API_URL } from "../services/api";
import { createAudioApi, retryTransient } from "../features/recording/chunkApi";
import {
  ChunkUploader,
  FLUSH_DEADLINE_MS,
  FLUSH_INTERVAL_MS,
} from "../features/recording/chunkUploader";
import {
  RecorderEngine,
  type RecordedSegment,
  type RecorderLike,
} from "../features/recording/recorderEngine";
import {
  IDLE_SNAPSHOT,
  type RecordingReply,
  type RecordingResult,
  type RecordingSnapshot,
} from "../features/recording/recordingProtocol";
import { decodeToSpeechWav } from "../features/recording/wav";

// Documento offscreen: é AQUI que a consulta é gravada (B29) e enviada em partes (B30).
//
// O popup é destruído quando fecha e levaria o MediaRecorder junto; este documento, criado
// pelo background.js, continua vivo até a gravação terminar. Documentos offscreen só têm a
// API chrome.runtime: o token é pedido ao background.js e o estado é publicado para ele, que
// o guarda em chrome.storage.session para o popup ler.

// Trechos menores que isto não têm áudio útil (mesmo corte que o popup já usava).
const MIN_SEGMENT_BYTES = 1000;

type ActiveRecording = {
  recordingId: string;
  patientId: string;
  consultationId: string;
  engine: RecorderEngine;
  uploader: ChunkUploader;
  /** Trechos são convertidos e enfileirados um por vez, na ordem em que fecham. */
  pipeline: Promise<void>;
  /** Maior sequência com áudio de verdade: é o total que o servidor deve esperar. */
  totalChunks: number;
  cancelled: boolean;
  tickTimer: ReturnType<typeof setInterval> | null;
};

let active: ActiveRecording | null = null;
let starting = false;
let lastResult: RecordingResult | null = null;

function snapshot(): RecordingSnapshot {
  if (!active) return { ...IDLE_SNAPSHOT, result: lastResult };
  const engine = active.engine.state;
  const upload = active.uploader.status;
  return {
    status: engine.status === "stopped" ? "finalizing" : engine.status,
    recordingId: active.recordingId,
    patientId: active.patientId,
    consultationId: active.consultationId,
    accumulatedMs: engine.accumulatedMs,
    resumedAt: engine.resumedAt,
    chunksSent: upload.sent.length,
    chunksPending: upload.pending.length,
    warning: upload.warning,
    result: null,
  };
}

function publish(): void {
  chrome.runtime
    .sendMessage({ target: "background", type: "recording:state", snapshot: snapshot() })
    .catch(() => {}); // o service worker pode estar acordando; o próximo estado corrige
}

async function getToken(): Promise<string | null> {
  try {
    const reply = await chrome.runtime.sendMessage({
      target: "background",
      type: "recording:get-token",
    });
    return typeof reply?.token === "string" ? reply.token : null;
  } catch {
    return null;
  }
}

const api = createAudioApi({ apiUrl: API_URL, getToken });

function microphoneError(error: unknown): string {
  const name = error instanceof Error ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "mic_denied";
  if (name === "NotFoundError") return "mic_not_found";
  return "mic_error";
}

async function start(patientId: string, consultationId: string): Promise<RecordingReply> {
  if (active || starting) return { ok: false, error: "already_recording", snapshot: snapshot() };
  starting = true;
  try {
    const ref = { consultationId, recordingId: crypto.randomUUID() };
    const recording: ActiveRecording = {
      ...ref,
      patientId,
      pipeline: Promise.resolve(),
      totalChunks: 0,
      cancelled: false,
      tickTimer: null,
      uploader: new ChunkUploader({ send: (chunk) => api.sendChunk(ref, chunk), onChange: publish }),
      engine: new RecorderEngine({
        getStream: () =>
          navigator.mediaDevices.getUserMedia({
            audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
          }),
        // O MediaRecorder real cumpre o contrato usado pela máquina; só os tipos dos eventos diferem.
        createRecorder: (stream) =>
          new MediaRecorder(stream as MediaStream) as unknown as RecorderLike,
        now: Date.now,
        onChange: publish,
        onSegment: (segment) => {
          recording.pipeline = recording.pipeline.then(() => handleSegment(recording, segment));
        },
      }),
    };

    // Antes de abrir o microfone: o estado publicado ao iniciar já precisa ser o desta gravação
    // (um estado "idle" faria o background.js fechar este documento).
    lastResult = null;
    active = recording;
    try {
      await recording.engine.start();
    } catch (error) {
      active = null;
      return { ok: false, error: microphoneError(error) };
    }
    // Reforço da conferência de limite/troca de parte feita a cada bloco de áudio gravado.
    recording.tickTimer = setInterval(() => recording.engine.tick(), 1000);
    publish();
    return { ok: true, snapshot: snapshot() };
  } finally {
    starting = false;
  }
}

async function handleSegment(recording: ActiveRecording, segment: RecordedSegment): Promise<void> {
  if (recording.cancelled) return;
  if (segment.blob.size >= MIN_SEGMENT_BYTES) {
    recording.totalChunks = segment.seq;
    try {
      const wav = await decodeToSpeechWav(segment.blob);
      recording.uploader.enqueue({ seq: segment.seq, blob: wav, durationMs: segment.durationMs });
    } catch (error) {
      // A parte fica faltando; as demais seguem (a consulta continua se uma parte falhar).
      console.error(`Parte ${segment.seq} não pôde ser convertida:`, error);
    }
  }
  if (segment.last) await finalize(recording);
}

// Depois de parar: reenvia o que ficou pendente, pede a transcrição e publica o resultado.
async function finalize(recording: ActiveRecording): Promise<void> {
  await recording.uploader.flush();
  if (recording.cancelled) return;

  const { sent } = recording.uploader.status;
  const result: RecordingResult = {
    recordingId: recording.recordingId,
    patientId: recording.patientId,
    consultationId: recording.consultationId,
    stopReason: recording.engine.state.stopReason ?? "manual",
    transcription: null,
    logEntry: null,
    error: null,
    missingChunks: [],
  };

  if (recording.totalChunks === 0) {
    result.error = "Gravação muito curta: nada foi enviado para transcrição.";
  } else if (sent.length === 0) {
    result.error = "Não foi possível enviar o áudio ao servidor. Verifique a conexão e grave novamente.";
  } else {
    try {
      const data = await retryTransient(() => api.transcribe(recording, recording.totalChunks), {
        deadlineMs: FLUSH_DEADLINE_MS,
        intervalMs: FLUSH_INTERVAL_MS,
      });
      const texto = String(data.transcription ?? "").trim();
      result.missingChunks = [...(data.chunks?.missing ?? []), ...(data.chunks?.failed ?? [])].sort(
        (a, b) => a - b
      );
      if (data.is_error || !texto) {
        result.error = "Não foi possível transcrever o áudio. Tente falar mais claro.";
      } else {
        result.transcription = texto;
        result.logEntry = data.log_entry ?? null;
      }
    } catch (error) {
      console.error("Falha ao transcrever a gravação:", error);
      result.error = "O áudio foi enviado, mas a transcrição falhou. Tente gravar novamente.";
    }
  }
  if (recording.cancelled) return;

  release(recording);
  lastResult = result;
  publish(); // estado "idle" com o resultado: o background.js guarda e fecha este documento
}

function release(recording: ActiveRecording): void {
  if (recording.tickTimer) clearInterval(recording.tickTimer);
  recording.tickTimer = null;
  if (active === recording) active = null;
}

// Descarta a gravação sem transcrever (o médico saiu da conta).
function cancel(): void {
  if (!active) return;
  const recording = active;
  recording.cancelled = true;
  recording.uploader.cancel();
  recording.engine.stop();
  release(recording);
  lastResult = null;
  publish();
}

type OffscreenMessage = {
  target?: string;
  type?: string;
  patientId?: string;
  consultationId?: string;
};

async function handle(message: OffscreenMessage): Promise<RecordingReply> {
  switch (message.type) {
    case "start":
      if (!message.patientId || !message.consultationId) return { ok: false, error: "invalid" };
      return start(message.patientId, message.consultationId);
    case "pause":
      active?.engine.pause();
      break;
    case "resume":
      active?.engine.resume();
      break;
    case "stop":
      active?.engine.stop();
      break;
    case "cancel":
      cancel();
      break;
    case "get-state":
      break;
    default:
      return { ok: false, error: "unknown_command" };
  }
  return { ok: true, snapshot: snapshot() };
}

chrome.runtime.onMessage.addListener((message: OffscreenMessage, _sender, sendResponse) => {
  if (message?.target !== "offscreen") return; // mensagens do popup para o background passam por aqui
  handle(message).then(sendResponse, () => sendResponse({ ok: false, error: "offscreen_error" }));
  return true; // resposta assíncrona
});
