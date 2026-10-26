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
