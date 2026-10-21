import { Dispatch, SetStateAction, useCallback, useEffect, useRef, useState } from "react";
import { botMessage, type Message, type TranscriptionLogItem } from "../shared/types";
import {
  microphonePermission,
  openMicrophonePermissionPage,
  readRecordingSnapshot,
  sendRecordingCommand,
  watchRecordingSnapshot,
} from "./recordingClient";
import {
  IDLE_SNAPSHOT,
  MAX_RECORDING_MS,
  elapsedMs,
  type RecordingResult,
  type RecordingSnapshot,
} from "./recordingProtocol";
import { useTranscriptionLog } from "./useTranscriptionLog";

export type RecordingParams = {
  patientId: string | null;
  consultationId: string | null;
  setMessages: Dispatch<SetStateAction<Message[]>>;
  handleSendMessage: (messageText: string) => Promise<void>;
};

const START_ERRORS: Record<string, string> = {
  mic_denied: "Permissão de microfone negada. Libere o microfone para a extensão e tente de novo.",
  mic_not_found: "Nenhum microfone encontrado. Conecte um microfone e tente de novo.",
  already_recording: "Já existe uma gravação em andamento.",
};

// Avisos sobre como a gravação terminou, exibidos no painel (as mensagens do chat são
// substituídas quando o histórico recarrega, então não servem para isso).
function outcomeNotices(result: RecordingResult): string[] {
  const notices: string[] = [];
  if (result.stopReason === "limit") {
    notices.push(
      `⏱️ A gravação atingiu o limite de ${MAX_RECORDING_MS / 60000} minutos e foi encerrada automaticamente.`
    );
  }
  if (result.stopReason === "device") {
    notices.push("🎙️ O microfone foi desconectado: a gravação foi encerrada nesse ponto.");
  }
  if (result.usedFallback) {
    notices.push(
      "⚠️ A transcrição utilizou um provedor alternativo (fallback). Revise o texto com atenção, pois a precisão pode ser menor."
    );
  }
  if (result.missingChunks.length > 0) {
    notices.push(
      `⚠️ Parte(s) ${result.missingChunks.join(", ")} do áudio não foram enviadas ou transcritas: a transcrição pode estar incompleta.`
    );
  }
  if (!result.transcription) {
    notices.push(`❌ ${result.error ?? "Não foi possível transcrever o áudio."}`);
  }
  return notices;
}

// Gravação da consulta (B29): iniciar, pausar, retomar, parar e cronômetro.
//
// A gravação em si acontece fora do popup (documento offscreen, ver recordingProtocol.ts).
// Este hook só espelha o estado guardado pelo background.js e envia comandos — por isso, ao
// reabrir o popup no meio de uma gravação, os controles e o cronômetro voltam onde estavam.
export function useAudioRecording({
  patientId,
  consultationId,
  setMessages,
  handleSendMessage,
}: RecordingParams) {
  const [snapshot, setSnapshot] = useState<RecordingSnapshot>(IDLE_SNAPSHOT);
  const [now, setNow] = useState(() => Date.now()); // relógio do cronômetro visual
  const [showRecordingHistory, setShowRecordingHistory] = useState<boolean>(false);
  const [hasRecordedAudio, setHasRecordedAudio] = useState<boolean>(false);
  const [notices, setNotices] = useState<string[]>([]);
  const [viewingLog, setViewingLog] = useState<TranscriptionLogItem | null>(null); // Armazena o log que está sendo lido
  const deliveredRef = useRef<string | null>(null);

  const {
  transcriptionLog,
  addTranscription,
  updateTranscription,
} = useTranscriptionLog(patientId);

  const isRecording = snapshot.status === "recording";
  const isPaused = snapshot.status === "paused";
  const isProcessing = snapshot.status === "finalizing";
  const isActive = snapshot.status !== "idle";

  // --- EFEITO 1: ESTADO DA GRAVAÇÃO (mantido fora do popup) ---
  useEffect(() => {
    let mounted = true;
    const apply = (next: RecordingSnapshot) => {
      if (mounted) setSnapshot(next);
    };
    readRecordingSnapshot().then(apply);
    const unwatch = watchRecordingSnapshot(apply);
    // Confere com o background se a gravação guardada ainda existe de fato.
    sendRecordingCommand({ type: "recording:sync" }).then((reply) => {
      if (reply.snapshot) apply(reply.snapshot);
    });
    return () => {
      mounted = false;
      unwatch();
    };
  }, []);

  // --- EFEITO 2: CRONÔMETRO VISUAL ---
  // O tempo vem sempre do estado (acumulado + trecho em curso); o intervalo só redesenha.
  useEffect(() => {
    if (!isRecording) return;
    setNow(Date.now());
    const interval = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(interval);
  }, [isRecording]);

  const elapsedTime = elapsedMs(snapshot, now) / 1000;

  // --- EFEITO 3: troca de consulta limpa os avisos da gravação anterior ---
  useEffect(() => {
    setHasRecordedAudio(false);
    setNotices([]);
  }, [consultationId]);

  // --- EFEITO 4: ENTREGA DA TRANSCRIÇÃO ---
  // A gravação pode terminar com o popup fechado: o resultado espera no estado até a consulta
  // dele estar aberta aqui, e então segue para o histórico e para o chat.
  const result = snapshot.result;
  useEffect(() => {
    if (!result || result.consultationId !== consultationId || result.patientId !== patientId) {
      return;
    }
    if (deliveredRef.current === result.recordingId) return;
    deliveredRef.current = result.recordingId;
    sendRecordingCommand({ type: "recording:ack-result" });

    setNotices(outcomeNotices(result));
    if (!result.transcription) return; // o motivo já está nos avisos do painel
    setHasRecordedAudio(true);
    if (result.logEntry) addTranscription(result.logEntry); // Atualiza lista visual de logs
    handleSendMessage(result.transcription); // Envia transcrição para o fluxo de chat
  }, [result, consultationId, patientId, addTranscription,patientId,
updateTranscription, handleSendMessage]);

  // --- Função para iniciar gravação ---
  const startAudioRecording = useCallback(async () => {
    if (!patientId || !consultationId || isActive) return;

    if ((await microphonePermission()) !== "granted") {
      openMicrophonePermissionPage();
      setMessages((prev) => [
        ...prev,
        botMessage(
          "🎙️ Autorize o microfone na aba que foi aberta e clique em “Iniciar gravação” novamente."
        ),
      ]);
      return;
    }

    setHasRecordedAudio(false);
    setNotices([]);
    const reply = await sendRecordingCommand({ type: "recording:start", patientId, consultationId });
    if (reply.snapshot) setSnapshot(reply.snapshot);
    if (!reply.ok) {
      const text = START_ERRORS[reply.error ?? ""] ?? "Erro ao acessar o microfone.";
      setMessages((prev) => [...prev, botMessage(text)]);
    }
  }, [patientId, consultationId, isActive, setMessages]);

  // --- Função para pausar/retomar gravação ---
  const togglePauseRecording = useCallback(() => {
    if (isRecording) sendRecordingCommand({ type: "recording:pause" });
    else if (isPaused) sendRecordingCommand({ type: "recording:resume" });
  }, [isRecording, isPaused]);

  // --- Função para parar gravação ---
  const stopAudioRecording = useCallback(() => {
    if (isRecording || isPaused) sendRecordingCommand({ type: "recording:stop" });
  }, [isRecording, isPaused]);

  // --- Função para ver histórico ---
  const toggleRecordingHistory = useCallback(() => {
    setShowRecordingHistory((prev) => !prev);
  }, []);

  return {
    isRecording,
    isPaused,
    isProcessing,
    isActive,
    patientId,
  updateTranscription,
    canStart: Boolean(patientId && consultationId) && !isActive,
    // A gravação pertence à consulta em que começou, mesmo que outra esteja aberta agora.
    isOtherConsultation: isActive && snapshot.consultationId !== consultationId,
    hasRecordedAudio,
    elapsedTime,
    pendingChunks: snapshot.chunksPending,
    rejectedChunks: snapshot.chunksRejected,
    uploadWarning: snapshot.warning,
    notices,
    showRecordingHistory,
    transcriptionLog,
    viewingLog,
    setViewingLog,
    startAudioRecording,
    togglePauseRecording,
    stopAudioRecording,
    toggleRecordingHistory,
  };
}
