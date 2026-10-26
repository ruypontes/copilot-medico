/**
 * SOAP (SoapV1) -> texto para o campo de evolução do PEP (B53).
 *
 * Uma seção por bloco, cada uma iniciada pelo marcador "Subjetivo:", "Objetivo:",
 * "Avaliação:" e "Plano:" no começo da linha: é o que o EsusPecAdapter usa para
 * distribuir o texto nos quatro campos do PEC (separarSecoesSoap). Hipóteses e
 * alertas entram na Avaliação; pendências, no Plano.
 *
 * Formato genérico para todos os PEPs. O B49 pode especializar o do Amplimed
 * pelo parâmetro `pep`, sem mudar quem chama.
 */

import type { SoapVersion } from "../features/shared/types";

const CONFIANCA: Record<string, string> = { baixa: "baixa", media: "média", alta: "alta" };

function lista(titulo: string, itens: string[]): string {
  return itens.length ? `\n${titulo}:\n${itens.map((item) => `- ${item}`).join("\n")}` : "";
}

export function formatSoapForPep(soap: SoapVersion, pep?: string): string {
  void pep; // reservado para formatos por PEP (B49)
  const hipoteses = soap.hipoteses.map((h) => {
    const cid = h.cid10 ? ` (CID-10 ${h.cid10})` : "";
    return `${h.descricao}${cid} — confiança ${CONFIANCA[h.confianca] ?? h.confianca}`;
  });
  return [
    `Subjetivo:\n${soap.subjetivo.trim()}`,
    `Objetivo:\n${soap.objetivo.trim()}`,
    `Avaliação:\n${soap.avaliacao.trim()}${lista("Hipóteses", hipoteses)}${lista("Alertas", soap.alertas)}`,
    `Plano:\n${soap.plano.trim()}${lista("Pendências", soap.pendencias)}`,
  ].join("\n\n");
}
