import { useCallback, useEffect, useState } from "react";
import { getTranscriptionLog } from "../../services/api";
import type { TranscriptionLogItem } from "../shared/types";

// Histórico de transcrições do paciente ativo.
export function useTranscriptionLog(patientId: string | null) {
  const [transcriptionLog, setTranscriptionLog] = useState<TranscriptionLogItem[]>([]); // Histórico separado

  // --- CARREGAR HISTÓRICO DE TRANSCRIÇÕES ---
  useEffect(() => {
    if (patientId) {
      getTranscriptionLog(patientId)
        .then((data) => {
          if (data.status === "success") {
            setTranscriptionLog(data.logs);
          }
        })
        .catch((err) => console.error("Erro ao carregar log de transcrições:", err));
    } else {
      setTranscriptionLog([]);
    }
  }, [patientId]);

  // Inclui a transcrição recém-concluída sem recarregar a lista. Se o popup reabriu depois
  // de a gravação terminar, a lista vinda do servidor já pode contê-la: não duplica.
  const addTranscription = useCallback((entry: TranscriptionLogItem) => {
    setTranscriptionLog((prev) =>
      prev.some((item) => item.id === entry.id) ? prev : [entry, ...prev]
    );
  }, []);

  return { transcriptionLog, addTranscription };
}
