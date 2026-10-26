/**
 * Ponte do popup com o content script da aba ativa (B53).
 *
 * O popup não acessa o DOM do PEP: pergunta ao content script qual PEP a aba
 * mostra e pede a escrita (src/content/comandosPep.ts). Sem content script na
 * aba (site que não é PEP, B51) o Chrome responde com erro de conexão, que
 * aqui vira "sem PEP".
 */

import type { PatientInfo } from "../../pep/pepAdapter";
import type {
  ComandoPep,
  RespostaEscritaPep,
  RespostaStatusPep,
} from "../../content/comandosPep";

export type PonteDoPep = {
  /** Id do PEP aberto na aba ativa ("esus-pec", "amplimed") ou null. */
  pepDaAba(): Promise<string | null>;
  /** Paciente do cabeçalho do PEP da aba, lido agora; null se não houver. */
  pacienteDaAba(): Promise<PatientInfo | null>;
  /** Escreve no PEP da aba; null se a aba não tem mais um PEP. */
  escrever(texto: string): Promise<RespostaEscritaPep | null>;
};

async function enviarParaAba<T>(comando: ComandoPep): Promise<T | null> {
  try {
    const [aba] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (aba?.id === undefined) return null;
    return ((await chrome.tabs.sendMessage(aba.id, comando)) as T | undefined) ?? null;
  } catch {
    return null; // nenhum content script respondeu: a aba não é de PEP
  }
}

export const ponteChrome: PonteDoPep = {
  async pepDaAba() {
    return (await enviarParaAba<RespostaStatusPep>({ type: "pep:status" }))?.pep ?? null;
  },
  async pacienteDaAba() {
    return (await enviarParaAba<RespostaStatusPep>({ type: "pep:status" }))?.paciente ?? null;
  },
  escrever(texto) {
    return enviarParaAba<RespostaEscritaPep>({ type: "pep:write", text: texto });
  },
};
