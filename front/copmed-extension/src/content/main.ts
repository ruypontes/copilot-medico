/**
 * Content script da extensão (B51/B52). Empacotado num arquivo só
 * (`dist/content.js`, ver vite.content.config.ts) e injetado apenas nos
 * domínios de `src/pep/dominios.ts`.
 */

import { pepRegistry } from "../pep/registry";
import { criarBotaoFlutuante } from "./botaoFlutuante";

// B52: botão flutuante só em página de PEP detectada.
criarBotaoFlutuante({
  registry: pepRegistry,
  enviar: (adaptador, campos) =>
    chrome.runtime.sendMessage({
      type: "pep:import",
      pep_origem: adaptador.id,
      campos,
      source_url: location.href,
    }),
}).iniciar();
