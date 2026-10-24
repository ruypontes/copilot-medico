import { MAX_RECORDING_MS } from "./recordingProtocol";
import type { useAudioRecording } from "./useAudioRecording";
import { formatDuration } from "./wav";
import TranscriptionFiles from "./TranscriptionFiles";
import TranscriptionViewer from "./TranscriptionViewer";

type Recording = ReturnType<typeof useAudioRecording>;

const MAX_DURATION_LABEL = formatDuration(MAX_RECORDING_MS / 1000);

// Área de gravação da consulta: controles, status e transcrições salvas.
export default function RecordingPanel({ recording }: { recording: Recording }) {
  const {
    patientId,
    updateTranscription,
    isRecording,
    isPaused,
    isProcessing,
    isActive,
    canStart,
    isOtherConsultation,
    hasRecordedAudio,
    elapsedTime,
    pendingChunks,
    rejectedChunks,
    uploadWarning,
    notices,
    showRecordingHistory,
    transcriptionLog,
    viewingLog,
    setViewingLog,
    startAudioRecording,
    togglePauseRecording,
    stopAudioRecording,
    toggleRecordingHistory,
  } = recording;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "10px",
        marginTop: "10px",
        padding: "0 10px",
        position: "relative", // Importante para transições se quiser animar depois
      }}
    >
      {/* === MODO LEITURA (Arquivo Aberto) === */}
      {viewingLog ? (
        <TranscriptionViewer log={viewingLog}
    patientId={patientId}
    onClose={() => setViewingLog(null)}
    onSaved={(updatedLog) => {
      updateTranscription(updatedLog);
      setViewingLog(updatedLog);
    }} />
      ) : (
        /* === MODO GRAVAÇÃO E LISTA (Padrão) === */
        <>
          {/* Controles de Gravação (Só aparecem se não estiver lendo) */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "10px",
            }}
          >
            {/* Um único botão principal: Iniciar quando parado; Pausar/Retomar durante a gravação */}
            <button
              onClick={isActive ? togglePauseRecording : startAudioRecording}
              disabled={isActive ? isProcessing : !canStart}
              style={{
                padding: "10px 15px",
                backgroundColor: isProcessing
                  ? "#cccccc"
                  : isRecording
                    ? "#FFA500"
                    : canStart || isPaused
                      ? "#4CAF50"
                      : "#cccccc",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: isProcessing || (!isActive && !canStart) ? "not-allowed" : "pointer",
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "5px",
              }}
            >
              {isRecording ? "⏸️ Pausar" : isPaused ? "▶️ Retomar" : "🎙️ Iniciar gravação"}
            </button>

            <button
              onClick={stopAudioRecording}
              disabled={(!isRecording && !isPaused) || isProcessing}
              style={{
                padding: "10px 15px",
                backgroundColor: "#e66060",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
                flex: 1,
              }}
            >
              ⏹️ Parar
            </button>

            <button
              onClick={toggleRecordingHistory}
              style={{
                padding: "10px 15px",
                backgroundColor: showRecordingHistory ? "#1976D2" : "#2196F3",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
              }}
            >
              {showRecordingHistory ? "📂 Ocultar Arq." : "📂 Transcrições"} ({transcriptionLog.length})
            </button>
          </div>

          {/* Status Messages */}
          <div style={{ textAlign: "center" }}>
            {isOtherConsultation && (
              <div style={{ color: "#FFA500", fontWeight: "bold" }}>
                ⚠️ Esta gravação pertence a outra consulta.
              </div>
            )}
            {isProcessing && (
              <div style={{ color: "orange", fontWeight: "bold" }}>
                ⏳ Processando...
                {pendingChunks > 0 && ` (enviando ${pendingChunks} parte(s) pendente(s))`}
              </div>
            )}
            {isRecording && (
              <div style={{ color: "#e66060", fontWeight: "bold" }}>
                ● Gravando... ({formatDuration(elapsedTime)})
              </div>
            )}
            {isPaused && (
              <div style={{ color: "#FFA500", fontWeight: "bold" }}>
                ⏸️ Pausado ({formatDuration(elapsedTime)})
              </div>
            )}
            {(isRecording || isPaused) && (
              <div style={{ color: "#888", fontSize: "0.8em" }}>
                Limite de {MAX_DURATION_LABEL}: ao atingi-lo a gravação para sozinha. Pode fechar
                esta janela, a gravação continua.
              </div>
            )}
            {/* Uma parte que falha não interrompe a consulta: fica na fila e é reenviada */}
            {isActive && pendingChunks > 0 && uploadWarning && (
              <div style={{ color: "#FFA500", fontSize: "0.85em" }}>
                {uploadWarning === "session_expired"
                  ? `⚠️ Sessão expirada: ${pendingChunks} parte(s) do áudio aguardando. Entre novamente para enviá-las.`
                  : `⚠️ ${pendingChunks} parte(s) do áudio aguardando reenvio. A gravação continua.`}
              </div>
            )}
            {/* Recusa definitiva: continuar gravando não adianta, o áudio não está sendo guardado */}
            {isActive && rejectedChunks > 0 && (
              <div style={{ color: "#e66060", fontSize: "0.85em", fontWeight: "bold" }}>
                ❌ O servidor recusou {rejectedChunks} parte(s) do áudio (consulta não encontrada ou
                sem acesso). Pare a gravação e selecione a consulta novamente.
              </div>
            )}
            {hasRecordedAudio && !isActive && (
              <div style={{ color: "#4CAF50", fontWeight: "bold" }}>✓ Arquivo salvo</div>
            )}
            {!isActive &&
              notices.map((notice) => (
                <div key={notice} style={{ color: "#FFA500", fontSize: "0.85em" }}>
                  {notice}
                </div>
              ))}
          </div>

          {/* Painel de Arquivos (Lista de Ícones) */}
          {showRecordingHistory && (
            <TranscriptionFiles
              logs={transcriptionLog}
              onOpen={(log) => {
                // Ao clicar no arquivo:
                // 1. Se estiver gravando, PAUSA para o usuário ler em paz
                if (isRecording) togglePauseRecording();
                // 2. Abre o modo leitura
                setViewingLog(log);
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
