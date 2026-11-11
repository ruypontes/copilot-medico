/**
 * Adaptador do e-SUS APS PEC (B50, US019-CA003).
 *
 * Lê nome/idade/sexo do cabeçalho do cidadão na tela de atendimento e
 * escreve no SOAP nativo do PEC (Subjetivo, Objetivo, Avaliação, Plano).
 * Seletores conferidos no PEC 5.5.28 rodando localmente (docs/11-esus-pec.md).
 *
 * Os campos do SOAP no PEC são editores Draft.js: mudar o DOM direto não
 * altera o estado do editor e o texto some ao salvar. Por isso a escrita
 * dispara um evento `paste`, que o Draft.js trata como uma colagem do
 * médico, e depois confere se o texto ficou no campo.
 */

import type { PatientInfo, PepAdapter, WriteEvolutionResult } from "./pepAdapter";

export type SecaoSoapPec = "subjetivo" | "objetivo" | "avaliacao" | "plano";

/** `data-testid` do campo de texto de cada seção do SOAP no PEC. */
const CAMPOS_SOAP: Record<SecaoSoapPec, string> = {
  subjetivo: "textFieldSubjetivo",
  objetivo: "observacoesObjetivo",
  avaliacao: "TextFieldObservacaoAvaliacao",
  plano: "textFieldPlano",
};

const ORDEM_SECOES: SecaoSoapPec[] = ["subjetivo", "objetivo", "avaliacao", "plano"];

/** Limite de cada campo do SOAP no PEC (o contador não conta quebras de linha). */
export const LIMITE_CARACTERES_CAMPO = 4000;

/** Marcador de seção no início da linha: "Subjetivo:", "Avaliação -", "**Plano:**"... */
const MARCADOR_SECAO = /^[ \t]*\**[ \t]*(subjetivo|objetivo|avalia[cç][aã]o|plano)[ \t]*\**[ \t]*[:\-–][ \t]*\**[ \t]*/gim;

const SEXOS = /\bSexo\s+(Masculino|Feminino|Indeterminado|Ignorado)\b/i;
const IDADE = /\b(\d+\s+(?:anos?|m[eê]s(?:es)?|dias?)(?:\s+e\s+\d+\s+(?:m[eê]s(?:es)?|dias?))?)\b/i;

function secaoDoMarcador(marcador: string): SecaoSoapPec {
  const m = marcador.toLowerCase();
  if (m.startsWith("subj")) return "subjetivo";
  if (m.startsWith("obj")) return "objetivo";
  if (m.startsWith("aval")) return "avaliacao";
  return "plano";
}

/**
 * Divide o texto do SOAP pelas seções do PEC. Texto sem nenhum marcador
 * (ou antes do primeiro) vai para o Subjetivo. Seções vazias são omitidas.
 */
export function separarSecoesSoap(texto: string): Partial<Record<SecaoSoapPec, string>> {
  const secoes: Partial<Record<SecaoSoapPec, string>> = {};
  const juntar = (secao: SecaoSoapPec, trecho: string) => {
    const limpo = trecho.trim();
    if (!limpo) return;
    secoes[secao] = secoes[secao] ? `${secoes[secao]}\n\n${limpo}` : limpo;
  };

  const marcadores = [...texto.matchAll(MARCADOR_SECAO)];
  if (marcadores.length === 0) {
    juntar("subjetivo", texto);
    return secoes;
  }

  juntar("subjetivo", texto.slice(0, marcadores[0].index));
  marcadores.forEach((marcador, i) => {
    const inicio = (marcador.index ?? 0) + marcador[0].length;
    const fim = i + 1 < marcadores.length ? marcadores[i + 1].index : texto.length;
    juntar(secaoDoMarcador(marcador[1]), texto.slice(inicio, fim));
  });
  return secoes;
}

/** Cabeçalho do cidadão: o `<header>` do atendimento, com o nome em `h2`. */
function cabecalhoDoCidadao(page: Document): HTMLElement | null {
  for (const header of page.querySelectorAll<HTMLElement>("header")) {
    if (header.querySelector("h2") && /Nasceu em/i.test(header.textContent ?? "")) return header;
  }
  return null;
}

/**
 * Texto do elemento com espaço entre os nós. No PEC os spans do cabeçalho
 * vêm colados ("Sexo Masculino46 anos"), e o `textContent` puro quebraria
 * as regex de sexo e idade.
 */
function textoSeparado(elemento: Element): string {
  const partes: string[] = [];
  const percorrer = (no: Node) => {
    if (no.nodeType === 3) partes.push(no.textContent ?? "");
    no.childNodes.forEach(percorrer);
  };
  percorrer(elemento);
  return partes.join(" ").replace(/\s+/g, " ");
}

function editorDaSecao(page: Document, secao: SecaoSoapPec): HTMLElement | null {
  return page.querySelector<HTMLElement>(
    `[data-testid="${CAMPOS_SOAP[secao]}"] [contenteditable="true"]`,
  );
}

/** Texto do editor Draft.js: um bloco por linha (o placeholder fica fora dos blocos). */
function textoDoEditor(editor: HTMLElement): string {
  const blocos = editor.querySelectorAll<HTMLElement>('[data-block="true"]');
  if (blocos.length === 0) return (editor.textContent ?? "").trim();
  return [...blocos].map((bloco) => bloco.textContent ?? "").join("\n").trim();
}

const contarCaracteres = (texto: string) => texto.replace(/\n/g, "").length;
const normalizar = (texto: string) => texto.replace(/\s+/g, " ").trim();

function criarEventoColar(page: Document, texto: string): Event {
  const janela = (page.defaultView ?? globalThis) as typeof globalThis;
  try {
    const dados = new janela.DataTransfer();
    dados.setData("text/plain", texto);
    return new janela.ClipboardEvent("paste", { clipboardData: dados, bubbles: true, cancelable: true });
  } catch {
    // Ambientes sem DataTransfer/ClipboardEvent construíveis (ex.: jsdom).
    const evento = new janela.Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(evento, "clipboardData", {
      value: {
        types: ["text/plain"],
        getData: (tipo: string) => (tipo === "text/plain" ? texto : ""),
      },
    });
    return evento;
  }
}

/** Põe o cursor no fim do editor, para a colagem acrescentar em vez de substituir. */
function cursorNoFim(page: Document, editor: HTMLElement): void {
  editor.focus();
  const selecao = page.getSelection?.();
  if (!selecao) return;
  const intervalo = page.createRange();
  intervalo.selectNodeContents(editor);
  intervalo.collapse(false);
  selecao.removeAllRanges();
  selecao.addRange(intervalo);
  page.dispatchEvent(new ((page.defaultView ?? globalThis) as typeof globalThis).Event("selectionchange"));
}

const proximoCiclo = () => new Promise<void>((resolve) => setTimeout(resolve, 50));

export function criarEsusPecAdapter(): PepAdapter {
  return {
    id: "esus-pec",

    detect(page: Document = document): boolean {
      try {
        return cabecalhoDoCidadao(page) !== null || editorDaSecao(page, "subjetivo") !== null;
      } catch {
        return false;
      }
    },

    readPatient(page: Document = document): PatientInfo | null {
      try {
        const cabecalho = cabecalhoDoCidadao(page);
        const nome = cabecalho?.querySelector("h2")?.textContent?.trim();
        if (!cabecalho || !nome) return null;

        const info: PatientInfo = { nome };
        const texto = textoSeparado(cabecalho);
        const idade = texto.match(IDADE)?.[1];
        const sexo = texto.match(SEXOS)?.[1];
        if (idade) info.idade = idade;
        if (sexo) info.sexo = sexo;
        return info;
      } catch {
        return null;
      }
    },

    readClinicalNotes(page: Document = document): Record<string, string> | null {
      try {
        const notas: Record<string, string> = {};
        for (const secao of ORDEM_SECOES) {
          const editor = editorDaSecao(page, secao);
          const texto = editor ? textoDoEditor(editor) : "";
          if (texto) notas[secao] = texto;
        }
        return Object.keys(notas).length > 0 ? notas : null;
      } catch {
        return null;
      }
    },

    async writeEvolution(text: string, page: Document = document): Promise<WriteEvolutionResult> {
      if (typeof text !== "string" || text.trim().length === 0) {
        return { ok: false, motivo: "texto_vazio" };
      }

      try {
        const secoes = separarSecoesSoap(text);
        const escritas = ORDEM_SECOES.filter((secao) => secoes[secao]).map((secao) => ({
          editor: editorDaSecao(page, secao),
          texto: secoes[secao] as string,
        }));

        // Confere tudo antes de escrever, para um campo ausente ou longo demais
        // não deixar o SOAP pela metade no prontuário.
        if (escritas.some(({ editor }) => editor === null)) {
          return { ok: false, motivo: "campo_nao_encontrado" };
        }
        for (const escrita of escritas) {
          const atual = textoDoEditor(escrita.editor as HTMLElement);
          const separador = atual ? "\n\n" : "";
          if (contarCaracteres(atual + separador + escrita.texto) > LIMITE_CARACTERES_CAMPO) {
            return { ok: false, motivo: "falha_ao_escrever" };
          }
        }

        for (const { editor, texto } of escritas) {
          const campo = editor as HTMLElement;
          const separador = textoDoEditor(campo) ? "\n\n" : "";
          cursorNoFim(page, campo);
          const evento = criarEventoColar(page, separador + texto);
          campo.dispatchEvent(evento);
          // Sem preventDefault o Draft.js não tratou a colagem: o estado do
          // editor não mudou, mesmo que o navegador tenha mexido no DOM.
          if (!evento.defaultPrevented) return { ok: false, motivo: "falha_ao_escrever" };
          await proximoCiclo();
          if (!normalizar(textoDoEditor(campo)).endsWith(normalizar(texto))) {
            return { ok: false, motivo: "falha_ao_escrever" };
          }
        }
        return { ok: true };
      } catch {
        // Nunca propaga a exceção: a mensagem poderia carregar texto do paciente.
        return { ok: false, motivo: "falha_ao_escrever" };
      }
    },
  };
}

export const esusPecAdapter: PepAdapter = criarEsusPecAdapter();
