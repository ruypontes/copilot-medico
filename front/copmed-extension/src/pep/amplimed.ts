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