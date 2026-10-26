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
 *
 * Antes de enviar, o paciente do cabeçalho do PEP é conferido com o
 * selecionado no Copilot (conferirPaciente.ts). Se não bater, nada é enviado
 * até o médico confirmar; se o PEP não mostrar o paciente, envia e avisa.
 */

import {
  conferirPaciente,
  mensagemDivergencia,
  mesmoPacienteNaTela,
} from "../pep/conferirPaciente";
import type { PatientInfo, PepAdapter, PepRegistry } from "../pep/pepAdapter";

export const ID_DO_BOTAO = "copmed-botao-pep";
export const TEXTO_DO_BOTAO = "Copilot: enviar dados do prontuário";
export const TEXTO_CONFIRMAR = "Enviar mesmo assim";
export const TEXTO_CANCELAR = "Cancelar";

export type ResultadoEnvio = { ok: boolean; mensagem?: string };

/** Paciente e consulta selecionados no popup (chrome.storage.local). */
export type SelecaoDaExtensao = { consultationId: string | null; paciente: PatientInfo | null };

export type OpcoesBotao = {
  registry: PepRegistry;
  /** Lê a seleção do popup na hora do clique (ela muda com o popup fechado). */
  selecaoAtual: () => Promise<SelecaoDaExtensao>;
  enviar: (
    adaptador: PepAdapter,
    campos: Record<string, string>,
    selecao: SelecaoDaExtensao,
  ) => Promise<ResultadoEnvio>;
  page?: Document;
  atrasoMs?: number;
  tempoDoAvisoMs?: number;
};

// Estilos dentro do shadow DOM: o CSS do PEP não altera o botão, e o do botão
// não vaza para o PEP.
const ESTILO = `
  .copmed-botao {
    position: fixed; right: 20px; bottom: 20px; z-index: 2147483647;
    padding: 10px 14px; border: 1px solid #114c0e; border-radius: 6px;
    background: #336b29; color: #fff; font: 600 13px/1.2 system-ui, sans-serif;
    cursor: pointer; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
  }
  .copmed-botao:disabled { opacity: 0.8; cursor: progress; }
  button:focus-visible { outline: 3px solid #93c5fd; outline-offset: 2px; }
  .copmed-alerta {
    position: fixed; right: 20px; bottom: 70px; z-index: 2147483647; max-width: 340px;
    padding: 12px 14px; border: 2px solid #b45309; border-radius: 6px;
    background: #fffbeb; color: #1f2937; font: 13px/1.4 system-ui, sans-serif;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  }
  .copmed-alerta p { margin: 0 0 10px; }
  .copmed-alerta div { display: flex; gap: 8px; justify-content: flex-end; }
  .copmed-alerta button {
    padding: 6px 10px; border-radius: 4px; border: 1px solid #6b7280;
    background: #fff; color: #1f2937; font: 600 12px/1.2 system-ui, sans-serif; cursor: pointer;
  }
  .copmed-alerta button.copmed-perigo { border-color: #b45309; background: #b45309; color: #fff; }
`;

export function criarBotaoFlutuante({
  registry,
  selecaoAtual,
  enviar,
  page = document,
  atrasoMs = 400,
  tempoDoAvisoMs = 3000,
}: OpcoesBotao) {
  let host: HTMLElement | null = null;
  let raiz: ShadowRoot | null = null;
  let alerta: HTMLElement | null = null;
  let adaptador: PepAdapter | null = null;
  let agendado: ReturnType<typeof setTimeout> | null = null;

  function criar() {
    host = page.createElement("div");
    host.id = ID_DO_BOTAO;
    // Fechado: o aviso de paciente trocado mostra o nome do paciente do
    // Copilot, que os scripts da página do PEP não devem conseguir ler.
    raiz = host.attachShadow({ mode: "closed" });
    const estilo = page.createElement("style");
    estilo.textContent = ESTILO;
    const botao = page.createElement("button");
    botao.type = "button";
    botao.className = "copmed-botao";
    botao.textContent = TEXTO_DO_BOTAO;
    botao.addEventListener("click", () => void clicar(botao));
    raiz.append(estilo, botao);
    (page.body ?? page.documentElement).appendChild(host);
  }

  function remover() {
    host?.remove();
    host = null;
    raiz = null;
    alerta = null;
  }

  function fecharAlerta() {
    alerta?.remove();
    alerta = null;
  }

  function avisar(botao: HTMLButtonElement, aviso: string) {
    botao.textContent = aviso;
    setTimeout(() => {
      botao.textContent = TEXTO_DO_BOTAO;
      botao.disabled = false;
    }, tempoDoAvisoMs);
  }

  /**
   * Mostra o paciente trocado e espera a decisão do médico. O botão principal
   * fica travado até ele escolher: o padrão é não enviar.
   */
  function perguntar(texto: string): Promise<boolean> {
    fecharAlerta();
    return new Promise((resolver) => {
      const caixa = page.createElement("div");
      caixa.className = "copmed-alerta";
      caixa.setAttribute("role", "alertdialog");
      caixa.setAttribute("aria-label", "Paciente diferente");
      const mensagem = page.createElement("p");
      mensagem.textContent = `${texto} Nada foi enviado.`;
      const acoes = page.createElement("div");
      const cancelar = page.createElement("button");
      cancelar.type = "button";
      cancelar.textContent = TEXTO_CANCELAR;
      const confirmar = page.createElement("button");
      confirmar.type = "button";
      confirmar.className = "copmed-perigo";
      confirmar.textContent = TEXTO_CONFIRMAR;
      cancelar.addEventListener("click", () => (fecharAlerta(), resolver(false)));
      confirmar.addEventListener("click", () => (fecharAlerta(), resolver(true)));
      acoes.append(cancelar, confirmar);
      caixa.append(mensagem, acoes);
      raiz?.append(caixa);
      alerta = caixa;
      cancelar.focus(); // Enter sem pensar cancela, não envia
    });
  }

  async function clicar(botao: HTMLButtonElement) {
    const atual = adaptador;
    if (!atual || botao.disabled) return;
    botao.disabled = true;
    botao.textContent = "Conferindo paciente...";
    try {
      if (!atual.readClinicalNotes(page)) return avisar(botao, "Nada para enviar nesta tela");

      const selecao = await selecaoAtual();
      const doPep = atual.readPatient(page);
      const conferencia = conferirPaciente(doPep, selecao.paciente);
      if (conferencia.situacao === "divergente") {
        if (!(await perguntar(mensagemDivergencia(conferencia)))) {
          return avisar(botao, "Envio cancelado");
        }
        // O PEP pode ter trocado de paciente enquanto o aviso estava aberto:
        // a confirmação vale só para o paciente que o médico viu no aviso.
        if (!mesmoPacienteNaTela(doPep, atual.readPatient(page))) {
          return avisar(botao, "O prontuário mudou de paciente: nada foi enviado");
        }
      }

      // Lidas só agora, do paciente que está na tela depois da conferência.
      const campos = atual.readClinicalNotes(page);
      if (!campos) return avisar(botao, "Nada para enviar nesta tela");
      botao.textContent = "Enviando...";
      const resultado = await enviar(atual, campos, selecao);
      if (!resultado.ok) return avisar(botao, resultado.mensagem || "Não foi possível enviar");
      avisar(
        botao,
        conferencia.situacao === "nao_conferido"
          ? "Dados enviados, sem conferir o paciente"
          : "Dados enviados ao Copilot",
      );
    } catch {
      fecharAlerta();
      avisar(botao, "Não foi possível enviar");
    }
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
    /** Shadow root (fechado) do botão, para os testes; null fora de PEP. */
    raiz: () => (host?.isConnected ? raiz : null),
  };
}
