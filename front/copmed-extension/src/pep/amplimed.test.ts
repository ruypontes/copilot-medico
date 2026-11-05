// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { amplimedAdapter, extractAmplimedData } from "./amplimed";
import { pepRegistry } from "./registry";
import { criarPaginaPec } from "../test/esusPecPagina";
import fixture from "../../tests/fixtures/pep/amplimed-consulta.html?raw";

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
