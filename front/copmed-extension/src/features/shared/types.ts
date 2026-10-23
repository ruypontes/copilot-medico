import { Key, ReactNode } from "react";

// --- Tipos ---
export type Message = {
  id: Key;
  text: ReactNode;
  sender: "user" | "bot";
  timestamp: string;
};

export type PatientListItem = {
  id: string;
  name: string;
};

export type ConsultationListItem = {
  id: string;
  title: string;
  date: string;
};

export type ChatHistoryMessage = {
  role?: string;
  parts?: Array<{ text?: string }>;
  timestamp?: string;
};

export type TranscriptionDialogueTurn = {
  role?: string;
  role_key?: string;
  text?: string;
};

export type TranscriptionLogItem = {
  id?: Key;
  consultation_id?: string | null;
  timestamp?: string;
  created_at?: string;
  duration?: string;
  text?: string;
  text_summary?: string;
  dialogue?: TranscriptionDialogueTurn[];
};

export type SoapHypothesis = {
  descricao: string;
  cid10: string | null;
  confianca: "baixa" | "media" | "alta";
};

export type SoapV1 = {
  subjetivo: string;
  objetivo: string;
  avaliacao: string;
  plano: string;
  hipoteses: SoapHypothesis[];
  alertas: string[];
  pendencias: string[];
};

export type SoapDocument = {
  id: string;
  consultation_id: string;
  versao_ia: SoapV1;
  versao_medico: SoapV1 | null;
  status: "gerado" | "editado" | "aprovado" | "inserido_no_pep";
  criado_em: string;
  aprovado_em: string | null;
};

export function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

// Mensagem do assistente exibida no chat (avisos, erros e confirmações).
export function botMessage(text: ReactNode): Message {
  return {
    id: Date.now(),
    text,
    sender: "bot",
    timestamp: new Date().toISOString(),
  };
}
