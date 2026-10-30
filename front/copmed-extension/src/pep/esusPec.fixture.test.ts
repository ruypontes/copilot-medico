// @vitest-environment jsdom
/**
 * EsusPecAdapter sobre as fixtures HTML do PEC (B54).
 *
 * `esusPec.test.ts` e `esusPec.contract.test.ts` (B50) já cobrem o adaptador com a página montada
 * em código. Aqui a entrada são os ARQUIVOS de `tests/fixtures/pep/`: o que um humano abre no
 * navegador. Cada teste parseia a fixture de novo, então nenhum enxerga o que outro alterou.
 */

import { afterEach, describe, expect, it } from "vitest";
import { simularDraft } from "../test/esusPecPagina";
import { FIXTURES_PEP, TEXTOS_PEC_PREENCHIDO, documentoDe, paginaPecDe } from "../test/fixturesPep";
import { LIMITE_CARACTERES_CAMPO, esusPecAdapter } from "./esusPec";

const { esusPecSoapVazio, esusPecSoapPreenchido, esusPecListaAtendimentos, paginaGenerica } = FIXTURES_PEP;

afterEach(() => {
  document.body.innerHTML = "";
});

describe("leitura do cidadão", () => {
  it("lê nome, idade e sexo do cabeçalho do atendimento", () => {
    expect(esusPecAdapter.readPatient(documentoDe(esusPecSoapVazio))).toEqual({
      nome: "Paciente Fictício Copmed",
      idade: "38 anos e 2 meses",
      sexo: "Feminino",
    });
  });

  it.each([esusPecListaAtendimentos, paginaGenerica])("%s: não é um atendimento, não há cidadão", (nome) => {
    expect(esusPecAdapter.readPatient(documentoDe(nome))).toBeNull();
  });
});

describe("leitura das notas", () => {
  it("fixture sem texto nenhum: null (o placeholder do editor não é nota)", () => {
    expect(esusPecAdapter.readClinicalNotes(documentoDe(esusPecSoapVazio))).toBeNull();
  });

  it("fixture preenchida: só as seções com texto, com as quebras de linha", () => {
    expect(esusPecAdapter.readClinicalNotes(documentoDe(esusPecSoapPreenchido))).toEqual({
      subjetivo: TEXTOS_PEC_PREENCHIDO.S,
      objetivo: TEXTOS_PEC_PREENCHIDO.O,
    });
  });

  it.each([esusPecListaAtendimentos, paginaGenerica])("%s: não há notas (nem o contenteditable de outro site conta)", (nome) => {
    expect(esusPecAdapter.readClinicalNotes(documentoDe(nome))).toBeNull();
  });
});

describe("escrita da evolução", () => {
  const SOAP_COMPLETO = [
    "Subjetivo:\nDor de cabeça.",
    "Objetivo:\nPA 110/70 mmHg.",
    "Avaliação:\nCefaleia tensional.",
    "Plano:\nAnalgésico e retorno.",
  ].join("\n\n");

  it("escreve as quatro seções nos quatro campos e dá para ler de volta", async () => {
    const page = paginaPecDe(esusPecSoapVazio);

    expect(await esusPecAdapter.writeEvolution(SOAP_COMPLETO, page)).toEqual({ ok: true });

    expect(esusPecAdapter.readClinicalNotes(page)).toEqual({
      subjetivo: "Dor de cabeça.",
      objetivo: "PA 110/70 mmHg.",
      avaliacao: "Cefaleia tensional.",
      plano: "Analgésico e retorno.",
    });
  });

  it("escrever só o Plano não mexe nas outras seções", async () => {
    const page = paginaPecDe(esusPecSoapVazio);

    expect(await esusPecAdapter.writeEvolution("Plano:\nRetorno em 7 dias.", page)).toEqual({ ok: true });

    expect(esusPecAdapter.readClinicalNotes(page)).toEqual({ plano: "Retorno em 7 dias." });
    expect(page.getElementById("placeholder-edS"), "o Subjetivo continua vazio, com o placeholder").not.toBeNull();
  });

  it("acrescenta ao texto que já está no campo, separado por uma linha em branco", async () => {
    const page = paginaPecDe(esusPecSoapPreenchido);

    expect(await esusPecAdapter.writeEvolution("Objetivo:\nSpO2 98%.", page)).toEqual({ ok: true });

    expect(esusPecAdapter.readClinicalNotes(page)).toEqual({
      subjetivo: TEXTOS_PEC_PREENCHIDO.S,
      objetivo: `${TEXTOS_PEC_PREENCHIDO.O}\n\nSpO2 98%.`,
    });
  });

  it("texto sem marcador de seção vai para o Subjetivo", async () => {
    const page = paginaPecDe(esusPecSoapVazio);

    expect(await esusPecAdapter.writeEvolution("Paciente retorna sem queixas.", page)).toEqual({ ok: true });

    expect(esusPecAdapter.readClinicalNotes(page)).toEqual({ subjetivo: "Paciente retorna sem queixas." });
  });

  it("não envia formulário nem clica em nada: quem confirma é o médico", async () => {
    const page = paginaPecDe(esusPecSoapVazio);
    const eventos: string[] = [];
    for (const tipo of ["submit", "click"]) page.addEventListener(tipo, () => eventos.push(tipo), true);

    await esusPecAdapter.writeEvolution(SOAP_COMPLETO, page);

    expect(eventos).toEqual([]);
  });

  it("texto em branco: texto_vazio, e a página fica como estava", async () => {
    const page = paginaPecDe(esusPecSoapVazio);

    expect(await esusPecAdapter.writeEvolution("   \n  ", page)).toEqual({ ok: false, motivo: "texto_vazio" });

    expect(esusPecAdapter.readClinicalNotes(page)).toBeNull();
  });
});

describe("falhas de escrita: tudo ou nada", () => {
  it("campo ausente em UMA seção: nenhuma seção é escrita", async () => {
    const page = paginaPecDe(esusPecSoapVazio);
    page.querySelector('[data-testid="textFieldPlano"]')?.remove();

    const resultado = await esusPecAdapter.writeEvolution("Subjetivo:\nQueixa.\n\nPlano:\nConduta.", page);

    expect(resultado).toEqual({ ok: false, motivo: "campo_nao_encontrado" });
    expect(esusPecAdapter.readClinicalNotes(page), "o Subjetivo não pode ter ficado escrito sozinho").toBeNull();
  });

  it("página que não é o atendimento: campo_nao_encontrado", async () => {
    expect(await esusPecAdapter.writeEvolution("Plano:\nX.", documentoDe(esusPecListaAtendimentos))).toEqual({
      ok: false,
      motivo: "campo_nao_encontrado",
    });
  });

  it("o Draft.js não trata a colagem: falha_ao_escrever, sem nada escrito", async () => {
    const page = paginaPecDe(esusPecSoapVazio, { semDraft: true });

    expect(await esusPecAdapter.writeEvolution("Subjetivo:\nQueixa.", page)).toEqual({
      ok: false,
      motivo: "falha_ao_escrever",
    });

    expect(esusPecAdapter.readClinicalNotes(page)).toBeNull();
  });

  /**
   * O navegador colou direto no DOM (o texto APARECE no campo), mas o Draft.js não tratou a colagem
   * (nenhum preventDefault): o estado do editor não mudou e, ao salvar, o texto some. Só o
   * `defaultPrevented` distingue isso de uma escrita boa, porque ver o texto no campo não basta.
   */
  it("o texto aparece no campo mas o Draft.js não tratou a colagem: falha_ao_escrever", async () => {
    const page = paginaPecDe(esusPecSoapVazio, { semDraft: true });
    const editor = page.querySelector<HTMLElement>('[data-testid="textFieldSubjetivo"] [contenteditable="true"]')!;
    editor.addEventListener("paste", () => {
      editor.querySelector<HTMLElement>('[data-block="true"]')!.textContent = "Queixa.";
    });

    const resultado = await esusPecAdapter.writeEvolution("Subjetivo:\nQueixa.", page);

    expect(resultado).toEqual({ ok: false, motivo: "falha_ao_escrever" });
  });

  it("passou do limite de caracteres do campo em UMA seção: nenhuma é escrita", async () => {
    const page = paginaPecDe(esusPecSoapVazio);
    const longo = "x".repeat(LIMITE_CARACTERES_CAMPO + 1);

    const resultado = await esusPecAdapter.writeEvolution(`Subjetivo:\nQueixa.\n\nPlano:\n${longo}`, page);

    expect(resultado).toEqual({ ok: false, motivo: "falha_ao_escrever" });
    expect(esusPecAdapter.readClinicalNotes(page)).toBeNull();
  });

  it("exatamente no limite ainda cabe", async () => {
    const page = paginaPecDe(esusPecSoapVazio);

    const resultado = await esusPecAdapter.writeEvolution(`Plano:\n${"x".repeat(LIMITE_CARACTERES_CAMPO)}`, page);

    expect(resultado).toEqual({ ok: true });
  });

  it("o resultado de uma falha nunca carrega o texto do paciente (LGPD)", async () => {
    const page = paginaPecDe(esusPecSoapVazio, { semDraft: true });

    const resultado = await esusPecAdapter.writeEvolution("Subjetivo:\nSEGREDO-DO-PACIENTE", page);

    expect(JSON.stringify(resultado)).not.toContain("SEGREDO-DO-PACIENTE");
  });
});

/** O content script chama o adaptador sem passar a página: vale o `document` global. */
describe("sem receber a página (como no content script)", () => {
  it("detecta, lê o cidadão e escreve no document global", async () => {
    document.body.innerHTML = documentoDe(esusPecSoapVazio).body.innerHTML;
    simularDraft(document);

    expect(esusPecAdapter.detect()).toBe(true);
    expect(esusPecAdapter.readPatient()?.nome).toBe("Paciente Fictício Copmed");
    expect(await esusPecAdapter.writeEvolution("Plano:\nRetorno.")).toEqual({ ok: true });
    expect(esusPecAdapter.readClinicalNotes()).toEqual({ plano: "Retorno." });
  });

  it("o document global sem PEC: detect false, leituras null", () => {
    document.body.innerHTML = documentoDe(paginaGenerica).body.innerHTML;

    expect(esusPecAdapter.detect()).toBe(false);
    expect(esusPecAdapter.readPatient()).toBeNull();
    expect(esusPecAdapter.readClinicalNotes()).toBeNull();
  });
});
