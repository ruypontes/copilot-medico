import { useCallback, useEffect, useRef, useState } from "react";
import { getRecommendations, type Suggestion } from "../../services/api";

// Sugestões da consulta (B38 / US020): pedidas sob demanda pelo médico, sobre as
// transcrições dos últimos N minutos. Ficam só em memória: não vão para o prontuário.

export const SUGGESTION_WINDOWS = [2, 5, 10, 15] as const;
export const DEFAULT_SUGGESTION_WINDOW = 5;

type SuggestionsState = {
  items: Suggestion[];
  /** Mensagem informativa da API (ex.: nenhuma transcrição na janela). */
  info: string | null;
  error: string | null;
  loading: boolean;
  /** Já houve um pedido para esta consulta (para mostrar "nenhuma sugestão"). */
  requested: boolean;
};

const EMPTY: SuggestionsState = { items: [], info: null, error: null, loading: false, requested: false };

export function useSuggestions(patientId: string | null, consultationId: string | null) {
  const [windowMinutes, setWindowMinutes] = useState<number>(DEFAULT_SUGGESTION_WINDOW);
  const [state, setState] = useState<SuggestionsState>(EMPTY);
  // Resposta de uma consulta anterior que chegue depois da troca é descartada.
  const currentKey = useRef<string | null>(null);

  useEffect(() => {
    currentKey.current = consultationId;
    setState(EMPTY);
  }, [patientId, consultationId]);

  const requestSuggestions = useCallback(async () => {
    if (!patientId || !consultationId) return;
    const key = consultationId;
    setState((previous) => ({ ...previous, loading: true, error: null, info: null }));
    try {
      const data = await getRecommendations({
        patient_id: patientId,
        consultation_id: consultationId,
        janela_min: windowMinutes,
      });
      if (currentKey.current !== key) return;
      setState({
        items: Array.isArray(data.itens) ? data.itens : [],
        info: typeof data.message === "string" ? data.message : null,
        error: null,
        loading: false,
        requested: true,
      });
    } catch (error) {
      if (currentKey.current !== key) return;
      setState({
        ...EMPTY,
        requested: true,
        error: error instanceof Error ? error.message : "Não foi possível gerar sugestões.",
      });
    }
  }, [patientId, consultationId, windowMinutes]);

  const clear = useCallback(() => setState(EMPTY), []);

  return { ...state, windowMinutes, setWindowMinutes, requestSuggestions, clear };
}
