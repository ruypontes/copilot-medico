/**
 * Botão flutuante do content script (B52 / US019-CA005 / D-02).
 *
 * Só aparece quando um adaptador do registry reconhece a página como PEP. Os
 * PEPs são SPAs (o e-SUS troca de tela sem recarregar), então a detecção é
 * refeita a cada mudança do DOM, com um pequeno atraso para não rodar a cada
 * nó inserido: o botão some ao sair do prontuário e volta ao entrar.
 *
 * O clique lê as notas pelo adaptador e as entrega a `enviar` (o background
 * manda para POST /api/consultations/<id>/pep-import). Nada é lido ou enviado
 * sem o clique do médico.
 */

import type { PepAdapter, PepRegistry } from "../pep/pepAdapter";

export const ID_DO_BOTAO = "copmed-botao-pep";
export const TEXTO_DO_BOTAO = "Copilot: enviar dados do prontuário";

export type ResultadoEnvio = { ok: boolean; mensagem?: string };

export type OpcoesBotao = {
  registry: PepRegistry;
  enviar: (adaptador: PepAdapter, campos: Record<string, string>) => Promise<ResultadoEnvio>;
  page?: Document;
  atrasoMs?: number;
  tempoDoAvisoMs?: number;
};

// Estilos dentro do shadow DOM: o CSS do PEP não altera o botão, e o do botão
// não vaza para o PEP.
const ESTILO = `
  button {
    position: fixed; right: 20px; bottom: 20px; z-index: 2147483647;
    padding: 10px 14px; border: 1px solid #114c0e; border-radius: 6px;
    background: #336b29; color: #fff; font: 600 13px/1.2 system-ui, sans-serif;
    cursor: pointer; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
  }
  button:disabled { opacity: 0.8; cursor: progress; }
  button:focus-visible { outline: 3px solid #93c5fd; outline-offset: 2px; }
`;

export function criarBotaoFlutuante({
  registry,
  enviar,
  page = document,
  atrasoMs = 400,
  tempoDoAvisoMs = 3000,
}: OpcoesBotao) {
  let host: HTMLElement | null = null;
  let adaptador: PepAdapter | null = null;
  let agendado: ReturnType<typeof setTimeout> | null = null;

  function criar() {
    host = page.createElement("div");
    host.id = ID_DO_BOTAO;
    const raiz = host.attachShadow({ mode: "open" });
    const estilo = page.createElement("style");
    estilo.textContent = ESTILO;
    const botao = page.createElement("button");
    botao.type = "button";
    botao.textContent = TEXTO_DO_BOTAO;
    botao.addEventListener("click", () => void clicar(botao));
    raiz.append(estilo, botao);
    (page.body ?? page.documentElement).appendChild(host);
  }

  function remover() {
    host?.remove();
    host = null;
  }

  async function clicar(botao: HTMLButtonElement) {
    const atual = adaptador;
    if (!atual || botao.disabled) return;
    botao.disabled = true;
    botao.textContent = "Enviando...";
    let aviso: string;
    try {
      const campos = atual.readClinicalNotes(page);
      if (!campos) {
        aviso = "Nada para enviar nesta tela";
      } else {
        const resultado = await enviar(atual, campos);
        aviso = resultado.ok ? "Dados enviados ao Copilot" : resultado.mensagem || "Não foi possível enviar";
      }
    } catch {
      aviso = "Não foi possível enviar";
    }
    botao.textContent = aviso;
    setTimeout(() => {
      botao.textContent = TEXTO_DO_BOTAO;
      botao.disabled = false;
    }, tempoDoAvisoMs);
  }

  /** Mostra ou esconde o botão conforme a página é (ou deixou de ser) um PEP. */
  function atualizar() {
    agendado = null;
    adaptador = registry.detect(page);
    if (adaptador && !host?.isConnected) criar();
    else if (!adaptador && host) remover();
  }

  const observador = new (page.defaultView ?? globalThis).MutationObserver(() => {
    if (agendado === null) agendado = setTimeout(atualizar, atrasoMs);
  });

  return {
    iniciar() {
      atualizar();
      observador.observe(page.documentElement, { childList: true, subtree: true });
    },
    parar() {
      observador.disconnect();
      if (agendado !== null) clearTimeout(agendado);
      remover();
    },
    atualizar,
    /** Adaptador da página agora (null fora de PEP). */
    adaptadorAtual: () => adaptador,
  };
}
