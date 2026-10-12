// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { extractAmplimedData } from "./amplimed";
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