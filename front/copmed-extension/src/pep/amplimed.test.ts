// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import type { SoapVersion } from "../features/shared/types";
import { amplimedAdapter, extractAmplimedData } from "./amplimed";
import { formatSoapForPep } from "./formatarSoap";
import { pepRegistry } from "./registry";
import { criarPaginaPec } from "../test/esusPecPagina";
import fixture from "../../tests/fixtures/pep/amplimed-consulta.html?raw";

const soap: SoapVersion = {
  subjetivo: "Febre há três dias.",
  objetivo: "Temperatura de 37,8 °C.",
  avaliacao: "Quadro compatível com virose.",
  plano: "Manter hidratação e observação.",
  hipoteses: [{ descricao: "Virose", cid10: "B34.9", confianca: "media" }],
  alertas: ["Retornar se houver piora."],
  pendencias: ["Reavaliar em três dias."],
};

const pagina = (html = fixture) => new DOMParser().parseFromString(html, "text/html");
const evolucao = (page: Document) => page.querySelector<HTMLTextAreaElement>('textarea[f_prontuario="evolucao"]')!;

describe("extractAmplimedData", () => {
  it("extrai os oito sinais vitais e as quatro notas da fixture Amplimed", () => {
    document.body.innerHTML = fixture;

    const result = extractAmplimedData(document);

    expect(result).toEqual({
      peso: "72.5",
      altura: "1.68",
      imc: "25.7",
      tempe: "37.8",
      freqres: "18",
      freqcar: "88",
      pas: "120",
      pad: "80",
      anamnese: "Paciente relata febre há 3 dias com tosse seca e dor de garganta.",
      exame_fisico: "Sem sinais de desidratação, murmúrio vesicular presente e sem roncos.",
      conclusao_diagnostica: "Quadro compatível com virose, manter hidratação e observação.",
      lista_problemas: "Febre, tosse, dor de garganta.",
    });
  });

  it("ignora campos vazios e valores desconhecidos", () => {
    document.body.innerHTML = '<input f_prontuario="peso" value=" "><input f_prontuario="cpf" value="123">';

    expect(extractAmplimedData(document)).toBeNull();
  });

  it("o campo de evolução não entra na leitura das notas", () => {
    const page = pagina();
    evolucao(page).value = "SOAP já inserido";
    expect(Object.values(extractAmplimedData(page) ?? {})).not.toContain("SOAP já inserido");
  });
});

describe("amplimedAdapter (B52)", () => {
  it("detecta o prontuário do Amplimed e lê as notas pela mesma extração", () => {
    document.body.innerHTML = fixture;
    expect(amplimedAdapter.detect(document)).toBe(true);
    expect(amplimedAdapter.readClinicalNotes(document)).toEqual(extractAmplimedData(document));
    expect(pepRegistry.detect(document)?.id).toBe("amplimed");
  });

  it("não detecta página comum nem o e-SUS PEC", () => {
    document.body.innerHTML = "<form><input name='senha'><textarea></textarea></form>";
    expect(amplimedAdapter.detect(document)).toBe(false);
    expect(amplimedAdapter.detect(criarPaginaPec())).toBe(false);
  });

  it("ainda não lê o paciente: devolve null em vez de inventar", () => {
    expect(amplimedAdapter.readPatient(pagina())).toBeNull();
  });
});

describe("formatSoapForPep para o Amplimed (B49)", () => {
  it("seções com a letra, e hipóteses, alertas e pendências em blocos no fim", () => {
    expect(formatSoapForPep(soap, "amplimed")).toBe(
      [
        "S - Subjetivo\nFebre há três dias.",
        "O - Objetivo\nTemperatura de 37,8 °C.",
        "A - Avaliação\nQuadro compatível com virose.",
        "P - Plano\nManter hidratação e observação.",
        "Hipóteses\n- Virose (CID-10: B34.9; confiança: média)",
        "Alertas\n- Retornar se houver piora.",
        "Pendências\n- Reavaliar em três dias.",
      ].join("\n\n"),
    );
  });

  it("omite blocos vazios e o CID-10 de hipótese sem código", () => {
    const texto = formatSoapForPep(
      { ...soap, hipoteses: [{ descricao: "Virose", cid10: null, confianca: "alta" }], alertas: [], pendencias: [] },
      "amplimed",
    );
    expect(texto.endsWith("Hipóteses\n- Virose (confiança: alta)")).toBe(true);
    expect(texto).not.toContain("Alertas");
    expect(texto).not.toContain("Pendências");
  });

  it("os outros PEPs continuam no formato padrão", () => {
    expect(formatSoapForPep(soap, "esus-pec")).toBe(formatSoapForPep(soap));
    expect(formatSoapForPep(soap, "esus-pec").startsWith("Subjetivo:\n")).toBe(true);
  });
});

describe("amplimedAdapter.writeEvolution (B49)", () => {
  it("escreve o SOAP formatado no campo de evolução da fixture e dispara input/change", async () => {
    const page = pagina();
    const campo = evolucao(page);
    const input = vi.fn();
    const change = vi.fn();
    campo.addEventListener("input", input);
    campo.addEventListener("change", change);

    const texto = formatSoapForPep(soap, "amplimed");
    expect(await amplimedAdapter.writeEvolution(texto, page)).toEqual({ ok: true });

    expect(campo.value).toBe(texto);
    expect(input).toHaveBeenCalledOnce();
    expect(change).toHaveBeenCalledOnce();
  });

  it("acrescenta ao que o médico já escreveu, sem apagar", async () => {
    const page = pagina();
    evolucao(page).value = "Anotação do médico.";
    expect(await amplimedAdapter.writeEvolution("S - Subjetivo\nFebre.", page)).toEqual({ ok: true });
    expect(evolucao(page).value).toBe("Anotação do médico.\n\nS - Subjetivo\nFebre.");
  });

  it("escreve no editor Summernote do campo e sincroniza o textarea escondido", async () => {
    const page = pagina(
      '<input f_prontuario="peso" value="70">' +
        '<textarea f_prontuario="evolucao" style="display:none"></textarea>' +
        '<div class="note-editor"><div class="note-editable" contenteditable="true"><p>Já escrito.</p></div></div>',
    );
    const editor = page.querySelector<HTMLElement>(".note-editor .note-editable")!;
    const input = vi.fn();
    editor.addEventListener("input", input);

    expect(await amplimedAdapter.writeEvolution("S - Subjetivo\n<b>Febre</b>", page)).toEqual({ ok: true });

    const linhas = [...editor.querySelectorAll("p")].map((p) => p.textContent);
    expect(linhas).toEqual(["Já escrito.", "", "S - Subjetivo", "<b>Febre</b>"]);
    expect(editor.querySelector("b")).toBeNull(); // texto, nunca HTML
    expect(input).toHaveBeenCalled();
    expect(evolucao(page).value).toBe(editor.innerHTML);
  });

  it("campo só leitura ou longo demais: falha_ao_escrever, sem mexer no campo", async () => {
    const travada = pagina();
    evolucao(travada).readOnly = true;
    expect(await amplimedAdapter.writeEvolution("Texto", travada)).toEqual({ ok: false, motivo: "falha_ao_escrever" });
    expect(evolucao(travada).value).toBe("");

    const curta = pagina();
    evolucao(curta).maxLength = 5;
    expect(await amplimedAdapter.writeEvolution("Texto longo", curta)).toEqual({ ok: false, motivo: "falha_ao_escrever" });
    expect(evolucao(curta).value).toBe("");
  });

  it("sem campo de evolução ou texto vazio: resultado explícito, nunca exceção", async () => {
    const semEvolucao = pagina(fixture.replace('<textarea f_prontuario="evolucao"></textarea>', ""));
    expect(await amplimedAdapter.writeEvolution("SOAP", semEvolucao)).toEqual({ ok: false, motivo: "campo_nao_encontrado" });
    expect(await amplimedAdapter.writeEvolution("   ", pagina())).toEqual({ ok: false, motivo: "texto_vazio" });
  });
});
