import type { SoapVersion } from "../features/shared/types";
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

function listSection(title: string, items: string[]): string[] {
  if (items.length === 0) return [];
  return [title, ...items.map((item) => `- ${item}`)];
}

/** Converte o SOAP estruturado em texto simples para o campo de evolução do Amplimed. */
export function formatSoapForPep(soap: SoapVersion): string {
  const sections = [
    ["S - Subjetivo", soap.subjetivo],
    ["O - Objetivo", soap.objetivo],
    ["A - Avaliação", soap.avaliacao],
    ["P - Plano", soap.plano],
  ].map(([title, content]) => `${title}\n${content.trim()}`);

  const hypotheses = soap.hipoteses.map((hypothesis) => {
    const details = [
      hypothesis.cid10 ? `CID-10: ${hypothesis.cid10}` : null,
      `confiança: ${hypothesis.confianca === "media" ? "média" : hypothesis.confianca}`,
    ].filter(Boolean);
    return `${hypothesis.descricao}${details.length ? ` (${details.join("; ")})` : ""}`;
  });

  const additionalSections = [
    listSection("Hipóteses", hypotheses),
    listSection("Alertas", soap.alertas),
    listSection("Pendências", soap.pendencias),
  ].filter((lines) => lines.length > 0).map((lines) => lines.join("\n"));

  return [...sections, ...additionalSections].join("\n\n");
}

export class AmplimedAdapter {
  readonly id = "amplimed";

  constructor(private readonly page: Document = document) {}

  writeEvolution(text: string): void {
    const field = this.page.querySelector<HTMLElement>(
      '[f_prontuario="evolucao"], [name="evolucao"], [data-field="evolucao"]'
    );
    if (!field) {
      throw new Error("Campo de evolução do Amplimed não encontrado.");
    }

    const pageWindow = this.page.defaultView;
    if (!pageWindow) {
      throw new Error("Não foi possível acessar a janela do prontuário Amplimed.");
    }

    if (field instanceof pageWindow.HTMLInputElement || field instanceof pageWindow.HTMLTextAreaElement) {
      const valueSetter = Object.getOwnPropertyDescriptor(
        Object.getPrototypeOf(field),
        "value"
      )?.set;
      if (valueSetter) valueSetter.call(field, text);
      else field.value = text;

      field.dispatchEvent(new pageWindow.Event("input", { bubbles: true }));
      field.dispatchEvent(new pageWindow.Event("change", { bubbles: true }));
      return;
    }

    if (field.isContentEditable || field.getAttribute("contenteditable") === "true") {
      field.textContent = text;
      field.dispatchEvent(new pageWindow.Event("input", { bubbles: true }));
      field.dispatchEvent(new pageWindow.Event("change", { bubbles: true }));
      return;
    }

    throw new Error("O campo de evolução do Amplimed não é editável.");
  }
}

/**
 * Adaptador do Amplimed (US019-CA002), por ora só de leitura: detecta a tela
 * do prontuário e lê os sinais vitais e as notas (B52). A escrita da evolução
 * é o B49; até lá `writeEvolution` responde `campo_nao_encontrado`, e o botão
 * "Inserir no prontuário" (B53) mostra que o Amplimed ainda não recebe o SOAP.
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
      return null; // o cabeçalho do paciente entra com o B49
    },

    readClinicalNotes(page: Document = document): Record<string, string> | null {
      try {
        return extractAmplimedData(page);
      } catch {
        return null;
      }
    },

    async writeEvolution(): Promise<WriteEvolutionResult> {
      return { ok: false, motivo: "campo_nao_encontrado" };
    },
  };
}

export const amplimedAdapter: PepAdapter = criarAmplimedAdapter();
