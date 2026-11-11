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
  speaker?: string;
  speaker_id?: string | number;
  start?: number;
  end?: number;
  inicio?: number;
  fim?: number;
  papel?: string;
  [key: string]: unknown;
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

// SOAP no esquema SoapV1 (B39, backend/soap/schema.py): versão da IA x versão do
// médico e o diff calculado pela API (B44).
export type SoapHypothesis = {
  descricao: string;
  cid10: string | null;
  confianca: "baixa" | "media" | "alta";
};

export type SoapVersion = {
  subjetivo: string;
  objetivo: string;
  avaliacao: string;
  plano: string;
  hipoteses: SoapHypothesis[];
  alertas: string[];
  pendencias: string[];
};

export type SoapDiffSnippet = {
  op: "igual" | "removido" | "adicionado";
  texto: string;
};

export type SoapDiffSection = {
  secao: keyof SoapVersion;
  titulo: string;
  tipo: "texto" | "lista";
  alterada: boolean;
  trechos: SoapDiffSnippet[];
};

export type SoapDiffResult = {
  alterado: boolean;
  secoes_alteradas: string[];
  secoes: SoapDiffSection[];
};

export type SoapDocument = {
  id: string;
  consultation_id: string;
  status: "gerado" | "editado" | "aprovado" | "inserido_no_pep";
  schema_version: string;
  prompt: { id: string; versao: string | null } | null;
  versao_ia: SoapVersion;
  versao_medico: SoapVersion | null;
  // O que o médico vê e aprova: a edição dele, ou a da IA se não editou.
  atual: SoapVersion;
  created_at: string | null;
  updated_at: string | null;
  approved_at: string | null;
  diff: SoapDiffResult | null;
};
export type WindowWithWebkitAudio = Window &
  typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
  };

export function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

// Mensagem do assistente exibida no chat (avisos, erros e confirma├º├Áes).
export function botMessage(text: ReactNode): Message {
  return {
    id: Date.now(),
    text,
    sender: "bot",
    timestamp: new Date().toISOString(),
  };
}
