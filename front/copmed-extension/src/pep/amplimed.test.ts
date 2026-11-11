// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import type { SoapVersion } from "../features/shared/types";
import { AmplimedAdapter, amplimedAdapter, extractAmplimedData, formatSoapForPep } from "./amplimed";
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
});

describe("AmplimedAdapter", () => {
  it("formata as seções SOAP e detalhes clínicos adicionais em texto simples", () => {
    expect(formatSoapForPep(soap)).toBe(
      [
        "S - Subjetivo\nFebre há três dias.",
        "O - Objetivo\nTemperatura de 37,8 °C.",
        "A - Avaliação\nQuadro compatível com virose.",
        "P - Plano\nManter hidratação e observação.",
        "Hipóteses\n- Virose (CID-10: B34.9; confiança: média)",
        "Alertas\n- Retornar se houver piora.",
        "Pendências\n- Reavaliar em três dias.",
      ].join("\n\n")
    );
  });

  it("escreve o SOAP no campo de evolução da fixture e dispara eventos de edição", () => {
    document.body.innerHTML = fixture;
    const field = document.querySelector<HTMLTextAreaElement>('[f_prontuario="evolucao"]');
    const inputListener = vi.fn();
    const changeListener = vi.fn();
    field?.addEventListener("input", inputListener);
    field?.addEventListener("change", changeListener);

    new AmplimedAdapter(document).writeEvolution(formatSoapForPep(soap));

    expect(field?.value).toContain("S - Subjetivo\nFebre há três dias.");
    expect(field?.value).toContain("P - Plano\nManter hidratação e observação.");
    expect(inputListener).toHaveBeenCalledOnce();
    expect(changeListener).toHaveBeenCalledOnce();
  });

  it("informa claramente quando o campo de evolução não existe", () => {
    document.body.innerHTML = "";

    expect(() => new AmplimedAdapter(document).writeEvolution("SOAP"))
      .toThrow("Campo de evolução do Amplimed não encontrado.");
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

  it("ainda não escreve a evolução (B49)", async () => {
    document.body.innerHTML = fixture;
    expect(await amplimedAdapter.writeEvolution("Subjetivo: x", document)).toEqual({
      ok: false,
      motivo: "campo_nao_encontrado",
    });
  });
});
