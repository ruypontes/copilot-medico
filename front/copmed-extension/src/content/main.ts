/**
 * Content script da extensão (B51/B52/B53). Empacotado num arquivo só
 * (`dist/content.js`, ver vite.content.config.ts) e injetado apenas nos
 * domínios de `src/pep/dominios.ts`.
 */

import { pepRegistry } from "../pep/registry";
import { criarBotaoFlutuante } from "./botaoFlutuante";
import { ehComandoPep, tratarComandoPep } from "./comandosPep";

// B52: botão flutuante só em página de PEP detectada.
criarBotaoFlutuante({
  registry: pepRegistry,
  // Seleção do popup (usePatients.ts). O nome só é comparado aqui, no navegador.
  selecaoAtual: async () => {
    const { consultationId, patientName } = await chrome.storage.local.get(["consultationId", "patientName"]);
    return {
      consultationId: typeof consultationId === "string" ? consultationId : null,
      paciente: typeof patientName === "string" ? { nome: patientName } : null,
    };
  },
  enviar: (adaptador, campos, selecao) =>
    chrome.runtime.sendMessage({
      type: "pep:import",
      pep_origem: adaptador.id,
      campos,
      source_url: location.href,
      // O background recusa se a consulta mudou depois da conferência.
      consultation_id: selecao.consultationId,
    }),
}).iniciar();

// B53: o popup pergunta qual PEP a aba mostra e pede a escrita do SOAP aprovado.
chrome.runtime.onMessage.addListener((mensagem, sender, sendResponse) => {
  // Só o popup da extensão comanda a escrita: mensagens de outra aba (com
  // sender.tab) ou de outra extensão são ignoradas.
  if (sender.id !== chrome.runtime.id || sender.tab || !ehComandoPep(mensagem)) return;
  // Frame sem PEP sai já (o detect é síncrono): se nenhum frame tiver PEP, o
  // popup recebe erro de conexão na hora em vez de esperar uma resposta.
  if (!pepRegistry.detect(document)) return;
  void tratarComandoPep(mensagem, pepRegistry).then(sendResponse);
  return true; // resposta assíncrona (a escrita espera o editor do PEP)
});
