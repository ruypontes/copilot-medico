import type { PatientInfo, PepAdapter, WriteEvolutionResult } from "./pepAdapter";

/** Extrai campos do Amplimed. Mantida sem dependencias externas para injecao via chrome.scripting. */
export function extractAmplimedData(page: Document = document): Record<string, string> | null {
  const fields: Record<string, string> = {};
  const vitalNames = ["peso", "altura", "imc", "tempe", "freqres", "freqcar", "pas", "pad"];

  for (const element of page.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
    "input[f_prontuario], textarea[f_prontuario], input.create-input, textarea.create-input"
  )) {
    const name = element.getAttribute("f_prontuario");
    if (!name || !vitalNames.includes(name)) continue;

    const value = element.value.trim();
    if (value) fields[name] = value;
  }

  const noteNames = ["anamnese", "exame_fisico", "conclusao_diagnostica", "lista_problemas"];
  const notes = page.querySelectorAll<HTMLElement>(
    ".note-editable[role='textbox'], .editable-notes"
  );
  notes.forEach((element, index) => {
    const name = noteNames[index];
    if (!name) return;
    const value = (element.innerText || element.textContent || "").trim();
    if (value) fields[name] = value;
  });

  return Object.keys(fields).length > 0 ? fields : null;
}

/**
 * Campo de evolução do Amplimed (B49). O Amplimed marca os campos do
 * prontuário com `f_prontuario` (como os sinais vitais acima); a evolução é
 * `f_prontuario="evolucao"`. `name`/`data-field` cobrem variações de tela.
 * Pode ser um textarea comum ou o textarea escondido de um editor Summernote,
 * cujo texto visível fica no `.note-editable` logo depois.
 */
const SELETOR_EVOLUCAO = [
  'textarea[f_prontuario="evolucao"]',
  '[contenteditable="true"][f_prontuario="evolucao"]',
  'textarea[name="evolucao"]',
  'textarea[data-field="evolucao"]',
].join(", ");

type Campo =
  | { tipo: "textarea"; elemento: HTMLTextAreaElement; editor: HTMLElement | null }
  | { tipo: "editavel"; elemento: HTMLElement };

function campoDeEvolucao(page: Document): Campo | null {
  const elemento = page.querySelector<HTMLElement>(SELETOR_EVOLUCAO);
  if (!elemento) return null;
  if (elemento.tagName === "TEXTAREA") {
    const proximo = elemento.nextElementSibling;
    const editor = proximo?.classList.contains("note-editor")
      ? proximo.querySelector<HTMLElement>(".note-editable")
      : null;
    return { tipo: "textarea", elemento: elemento as HTMLTextAreaElement, editor };
  }
  return { tipo: "editavel", elemento };
}

/** Texto de um editor rico: um parágrafo (ou bloco) por linha. */
function textoDoEditavel(editor: HTMLElement): string {
  const blocos = editor.querySelectorAll(":scope > p, :scope > div");
  if (blocos.length === 0) return (editor.innerText || editor.textContent || "").trim();
  return [...blocos].map((bloco) => bloco.textContent ?? "").join("\n").trim();
}

/** Texto atual do campo, para acrescentar em vez de apagar o que o médico já escreveu. */
function textoDoCampo(campo: Campo): string {
  if (campo.tipo === "editavel") return textoDoEditavel(campo.elemento);
  return campo.editor ? textoDoEditavel(campo.editor) : campo.elemento.value.trim();
}

function disparar(page: Document, elemento: HTMLElement, ...tipos: string[]): void {
  const janela = (page.defaultView ?? globalThis) as typeof globalThis;
  for (const tipo of tipos) elemento.dispatchEvent(new janela.Event(tipo, { bubbles: true }));
}

/**
 * Grava no textarea pelo setter nativo do `value`: frameworks que controlam o
 * campo (React, Vue) ignoram uma atribuição direta, mas tratam o `input`.
 */
function escreverNoTextarea(page: Document, campo: HTMLTextAreaElement, valor: string): void {
  const janela = (page.defaultView ?? globalThis) as typeof globalThis;
  const setter = Object.getOwnPropertyDescriptor(janela.HTMLTextAreaElement.prototype, "value")?.set;
  if (setter) setter.call(campo, valor);
  else campo.value = valor;
  disparar(page, campo, "input", "change");
}

/** Um parágrafo por linha, sempre como texto: nada do SOAP vira HTML. */
function acrescentarParagrafos(page: Document, editor: HTMLElement, texto: string): void {
  for (const linha of texto.split("\n")) {
    const paragrafo = page.createElement("p");
    if (linha) paragrafo.textContent = linha;
    else paragrafo.appendChild(page.createElement("br"));
    editor.appendChild(paragrafo);
  }
  disparar(page, editor, "input", "keyup", "change");
}

const normalizar = (texto: string) => texto.replace(/\s+/g, " ").trim();

/**
 * Adaptador do Amplimed (US019-CA002): detecta a tela do prontuário, lê os
 * sinais vitais e as notas (B52) e escreve o SOAP no campo de evolução (B49).
 *
 * `readPatient` ainda devolve null: o cabeçalho do paciente do Amplimed não
 * foi conferido numa conta real. Sem ele o "Inserir no prontuário" escreve e
 * avisa que não conferiu o paciente (conferirPaciente.ts).
 */
export function criarAmplimedAdapter(): PepAdapter {
  return {
    id: "amplimed",

    detect(page: Document = document): boolean {
      try {
        return page.querySelector("input[f_prontuario], .note-editable[role='textbox']") !== null;
      } catch {
        return false;
      }
    },

    readPatient(): PatientInfo | null {
      return null;
    },

    readClinicalNotes(page: Document = document): Record<string, string> | null {
      try {
        return extractAmplimedData(page);
      } catch {
        return null;
      }
    },

    async writeEvolution(text: string, page: Document = document): Promise<WriteEvolutionResult> {
      if (typeof text !== "string" || text.trim().length === 0) {
        return { ok: false, motivo: "texto_vazio" };
      }

      try {
        const campo = campoDeEvolucao(page);
        if (!campo) return { ok: false, motivo: "campo_nao_encontrado" };

        // Campo travado pela tela (atendimento finalizado, só leitura): não força.
        const travado =
          campo.tipo === "textarea"
            ? campo.editor
              ? campo.editor.getAttribute("contenteditable") === "false"
              : campo.elemento.disabled || campo.elemento.readOnly
            : campo.elemento.getAttribute("contenteditable") !== "true";
        if (travado) return { ok: false, motivo: "falha_ao_escrever" };

        // Acrescenta ao fim: a evolução pode já ter texto do médico.
        const atual = textoDoCampo(campo);
        const separador = atual ? "\n\n" : "";

        if (campo.tipo === "textarea" && !campo.editor) {
          const limite = campo.elemento.maxLength;
          const novo = campo.elemento.value.replace(/\s+$/, "") + separador + text;
          if (limite > 0 && novo.length > limite) return { ok: false, motivo: "falha_ao_escrever" };
          escreverNoTextarea(page, campo.elemento, novo);
        } else {
          const editor = campo.tipo === "textarea" ? (campo.editor as HTMLElement) : campo.elemento;
          acrescentarParagrafos(page, editor, (separador ? "\n" : "") + text);
          // Summernote: o textarea escondido é o que vai no formulário.
          if (campo.tipo === "textarea") escreverNoTextarea(page, campo.elemento, editor.innerHTML);
        }

        // Só confirma se o texto ficou de fato no campo.
        if (!normalizar(textoDoCampo(campo)).endsWith(normalizar(text))) {
          return { ok: false, motivo: "falha_ao_escrever" };
        }
        return { ok: true };
      } catch {
        // Nunca propaga a exceção: a mensagem poderia carregar texto do paciente.
        return { ok: false, motivo: "falha_ao_escrever" };
      }
    },
  };
}

export const amplimedAdapter: PepAdapter = criarAmplimedAdapter();
