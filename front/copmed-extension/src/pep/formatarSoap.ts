/**
 * SOAP (SoapV1) -> texto para o campo de evolução do PEP (B53 / B49).
 *
 * Formato padrão (e-SUS PEC e PEPs sem formato próprio): uma seção por bloco,
 * cada uma iniciada pelo marcador "Subjetivo:", "Objetivo:", "Avaliação:" e
 * "Plano:" no começo da linha. É o que o EsusPecAdapter usa para distribuir o
 * texto nos quatro campos do PEC (separarSecoesSoap). Hipóteses e alertas
 * entram na Avaliação; pendências, no Plano.
 *
 * Amplimed (B49): o SOAP inteiro vai para um campo só (a evolução), então cada
 * seção ganha um título com a letra ("S - Subjetivo") e hipóteses, alertas e
 * pendências viram blocos próprios no fim, mais fáceis de ler no prontuário.
 */

import type { SoapHypothesis, SoapVersion } from "../features/shared/types";

const CONFIANCA: Record<string, string> = { baixa: "baixa", media: "média", alta: "alta" };

function lista(titulo: string, itens: string[]): string {
  return itens.length ? `\n${titulo}:\n${itens.map((item) => `- ${item}`).join("\n")}` : "";
}

function hipotesePadrao(h: SoapHypothesis): string {
  const cid = h.cid10 ? ` (CID-10 ${h.cid10})` : "";
  return `${h.descricao}${cid} — confiança ${CONFIANCA[h.confianca] ?? h.confianca}`;
}

function formatoPadrao(soap: SoapVersion): string {
  return [
    `Subjetivo:\n${soap.subjetivo.trim()}`,
    `Objetivo:\n${soap.objetivo.trim()}`,
    `Avaliação:\n${soap.avaliacao.trim()}${lista("Hipóteses", soap.hipoteses.map(hipotesePadrao))}${lista("Alertas", soap.alertas)}`,
    `Plano:\n${soap.plano.trim()}${lista("Pendências", soap.pendencias)}`,
  ].join("\n\n");
}

function blocoAmplimed(titulo: string, itens: string[]): string[] {
  return itens.length ? [`${titulo}\n${itens.map((item) => `- ${item}`).join("\n")}`] : [];
}

function formatoAmplimed(soap: SoapVersion): string {
  const hipoteses = soap.hipoteses.map((h) => {
    const detalhes = [h.cid10 ? `CID-10: ${h.cid10}` : null, `confiança: ${CONFIANCA[h.confianca] ?? h.confianca}`];
    return `${h.descricao} (${detalhes.filter(Boolean).join("; ")})`;
  });
  return [
    `S - Subjetivo\n${soap.subjetivo.trim()}`,
    `O - Objetivo\n${soap.objetivo.trim()}`,
    `A - Avaliação\n${soap.avaliacao.trim()}`,
    `P - Plano\n${soap.plano.trim()}`,
    ...blocoAmplimed("Hipóteses", hipoteses),
    ...blocoAmplimed("Alertas", soap.alertas),
    ...blocoAmplimed("Pendências", soap.pendencias),
  ].join("\n\n");
}

export function formatSoapForPep(soap: SoapVersion, pep?: string): string {
  return pep === "amplimed" ? formatoAmplimed(soap) : formatoPadrao(soap);
}
