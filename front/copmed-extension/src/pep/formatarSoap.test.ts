// @vitest-environment jsdom
/**
 * formatSoapForPep (B53): o texto do SOAP aprovado que vai para o prontuário.
 *
 * O formatador e o `separarSecoesSoap` do e-SUS PEC precisam concordar: o que um escreve, o outro
 * divide nos quatro campos. Um marcador que o formatador emite e o separador não entende faria o
 * texto inteiro cair no Subjetivo, sem erro. Os testes de ida e volta abaixo existem por isso.
 */

import { describe, expect, it } from "vitest";
import type { SoapVersion } from "../features/shared/types";
import { FIXTURES_PEP, paginaPecDe } from "../test/fixturesPep";
import { LIMITE_CARACTERES_CAMPO, esusPecAdapter, separarSecoesSoap } from "./esusPec";
import { formatSoapForPep } from "./formatarSoap";

const SOAP: SoapVersion = {
  subjetivo: "  Febre há 3 dias, dor retro-orbitária.  ",
  objetivo: "Temperatura 38,9 °C.",
  avaliacao: "Síndrome febril aguda.",
  plano: "Hidratação oral e hemograma.",
  hipoteses: [
    { descricao: "Dengue", cid10: "A90", confianca: "media" },
    { descricao: "Virose inespecífica", cid10: null, confianca: "baixa" },
  ],
  alertas: ["Retornar se houver sangramento."],
  pendencias: ["Hemograma de controle"],
};

const SOAP_SEM_LISTAS: SoapVersion = { ...SOAP, hipoteses: [], alertas: [], pendencias: [] };

describe("formato do texto", () => {
  it("quatro blocos com marcador, nesta ordem, separados por linha em branco", () => {
    expect(formatSoapForPep(SOAP_SEM_LISTAS)).toBe(
      [
        "Subjetivo:\nFebre há 3 dias, dor retro-orbitária.",
        "Objetivo:\nTemperatura 38,9 °C.",
        "Avaliação:\nSíndrome febril aguda.",
        "Plano:\nHidratação oral e hemograma.",
      ].join("\n\n"),
    );
  });

  it("hipóteses e alertas entram na Avaliação; pendências, no Plano", () => {
    expect(formatSoapForPep(SOAP)).toBe(
      [
        "Subjetivo:\nFebre há 3 dias, dor retro-orbitária.",
        "Objetivo:\nTemperatura 38,9 °C.",
        [
          "Avaliação:\nSíndrome febril aguda.",
          "Hipóteses:",
          "- Dengue (CID-10 A90) — confiança média",
          "- Virose inespecífica — confiança baixa",
          "Alertas:",
          "- Retornar se houver sangramento.",
        ].join("\n"),
        ["Plano:\nHidratação oral e hemograma.", "Pendências:", "- Hemograma de controle"].join("\n"),
      ].join("\n\n"),
    );
  });

  it("hipótese sem CID-10 não ganha parênteses; confiança 'alta' é rotulada", () => {
    const texto = formatSoapForPep({
      ...SOAP_SEM_LISTAS,
      hipoteses: [{ descricao: "Sinusite", cid10: null, confianca: "alta" }],
    });

    expect(texto).toContain("- Sinusite — confiança alta");
    expect(texto).not.toContain("()");
  });

  it("listas vazias não deixam título solto", () => {
    const texto = formatSoapForPep(SOAP_SEM_LISTAS);

    for (const titulo of ["Hipóteses:", "Alertas:", "Pendências:"]) expect(texto).not.toContain(titulo);
  });

  it("tira os espaços das pontas de cada seção", () => {
    expect(formatSoapForPep(SOAP_SEM_LISTAS)).toContain("Subjetivo:\nFebre há 3 dias, dor retro-orbitária.\n\nObjetivo:");
  });

  it("hoje o formato é o mesmo para qualquer PEP (a B49 pode especializar o do Amplimed)", () => {
    expect(formatSoapForPep(SOAP, "amplimed")).toBe(formatSoapForPep(SOAP, "esus-pec"));
    expect(formatSoapForPep(SOAP, "amplimed")).toBe(formatSoapForPep(SOAP));
  });
});

describe("ida e volta com o separador de seções do e-SUS PEC", () => {
  it("o separador devolve as quatro seções, sem vazar uma para dentro da outra", () => {
    const secoes = separarSecoesSoap(formatSoapForPep(SOAP));

    expect(secoes.subjetivo).toBe("Febre há 3 dias, dor retro-orbitária.");
    expect(secoes.objetivo).toBe("Temperatura 38,9 °C.");
    expect(secoes.avaliacao).toBe(
      [
        "Síndrome febril aguda.",
        "Hipóteses:",
        "- Dengue (CID-10 A90) — confiança média",
        "- Virose inespecífica — confiança baixa",
        "Alertas:",
        "- Retornar se houver sangramento.",
      ].join("\n"),
    );
    expect(secoes.plano).toBe("Hidratação oral e hemograma.\nPendências:\n- Hemograma de controle");
  });

  it("os títulos das listas (Hipóteses, Alertas, Pendências) não são lidos como seção nova", () => {
    expect(Object.keys(separarSecoesSoap(formatSoapForPep(SOAP))).sort()).toEqual(
      ["avaliacao", "objetivo", "plano", "subjetivo"],
    );
  });
});

describe("do SOAP aprovado até os campos do e-SUS PEC (fixture)", () => {
  it("escreve nas quatro abas e dá para ler de volta", async () => {
    const page = paginaPecDe(FIXTURES_PEP.esusPecSoapVazio);

    expect(await esusPecAdapter.writeEvolution(formatSoapForPep(SOAP), page)).toEqual({ ok: true });

    expect(esusPecAdapter.readClinicalNotes(page)).toEqual(separarSecoesSoap(formatSoapForPep(SOAP)));
  });

  it("um Plano maior que o limite do campo: nada é escrito", async () => {
    const page = paginaPecDe(FIXTURES_PEP.esusPecSoapVazio);
    const grande: SoapVersion = { ...SOAP, plano: "x".repeat(LIMITE_CARACTERES_CAMPO + 1) };

    expect(await esusPecAdapter.writeEvolution(formatSoapForPep(grande), page)).toEqual({
      ok: false,
      motivo: "falha_ao_escrever",
    });
    expect(esusPecAdapter.readClinicalNotes(page)).toBeNull();
  });
});
