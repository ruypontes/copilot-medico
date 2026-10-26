/**
 * Comandos que o popup envia ao content script da aba (B53 / US019-CA006).
 *
 * - `pep:status`: qual PEP a aba mostra (o botão "Inserir no prontuário" só
 *   habilita com um PEP aberto).
 * - `pep:write`: escreve o SOAP aprovado pelo adaptador detectado. Só existe
 *   como resposta a um clique do médico no popup: nada é escrito sozinho.
 *
 * Um frame sem PEP não responde (devolve null), para que a resposta venha do
 * frame que tem o prontuário. As mensagens com os tipos e respostas ficam aqui
 * para o popup (pepDaAba.ts) e o content script usarem o mesmo contrato.
 */

import type { PepRegistry, WriteEvolutionResult } from "../pep/pepAdapter";

export type ComandoPep = { type: "pep:status" } | { type: "pep:write"; text: string };

export type RespostaStatusPep = { pep: string };
export type RespostaEscritaPep = { pep: string; resultado: WriteEvolutionResult };

export function ehComandoPep(mensagem: unknown): mensagem is ComandoPep {
  if (typeof mensagem !== "object" || mensagem === null) return false;
  const { type, text } = mensagem as { type?: unknown; text?: unknown };
  return type === "pep:status" || (type === "pep:write" && typeof text === "string");
}

export async function tratarComandoPep(
  comando: ComandoPep,
  registry: PepRegistry,
  page: Document = document,
): Promise<RespostaStatusPep | RespostaEscritaPep | null> {
  const adaptador = registry.detect(page);
  if (!adaptador) return null;
  if (comando.type === "pep:status") return { pep: adaptador.id };
  return { pep: adaptador.id, resultado: await adaptador.writeEvolution(comando.text, page) };
}
