// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { criarEsusPecAdapter, LIMITE_CARACTERES_CAMPO, separarSecoesSoap } from "./esusPec";
import { pepRegistry } from "./registry";
import { criarPaginaPec } from "../test/esusPecPagina";

const adaptador = criarEsusPecAdapter();

const SOAP = [
  "Subjetivo: Tosse seca há três dias.",
  "Nega febre.",
  "Objetivo: Ausculta pulmonar sem ruídos adventícios.",
  "Avaliação: Infecção de vias aéreas superiores.",
  "Plano: Hidratação e retorno se febre.",
].join("\n");

describe("separarSecoesSoap", () => {
  it("divide o texto pelas quatro seções do PEC", () => {
    expect(separarSecoesSoap(SOAP)).toEqual({
      subjetivo: "Tosse seca há três dias.\nNega febre.",
      objetivo: "Ausculta pulmonar sem ruídos adventícios.",
      avaliacao: "Infecção de vias aéreas superiores.",
      plano: "Hidratação e retorno se febre.",
    });
  });

  it("aceita marcador em negrito, sem acento e com hífen", () => {
    expect(separarSecoesSoap("**Avaliacao:** Cefaleia.\nPLANO - Dipirona.")).toEqual({
      avaliacao: "Cefaleia.",
      plano: "Dipirona.",
    });
  });

  it("texto sem marcador vai inteiro para o Subjetivo", () => {
    expect(separarSecoesSoap("  Evolução livre.\nSegunda linha. ")).toEqual({
      subjetivo: "Evolução livre.\nSegunda linha.",
    });
  });

  it("palavra de seção no meio da frase não é marcador", () => {
    expect(separarSecoesSoap("Subjetivo: discutido o plano: repouso.")).toEqual({
      subjetivo: "discutido o plano: repouso.",
    });
  });
});

describe("EsusPecAdapter na tela de atendimento", () => {
  it("está registrado no registry com o id esus-pec", () => {
    expect(pepRegistry.get("esus-pec")).toBeDefined();
    expect(pepRegistry.detect(criarPaginaPec())?.id).toBe("esus-pec");
  });

  it("lê nome, idade e sexo do cabeçalho do cidadão", () => {
    expect(adaptador.readPatient(criarPaginaPec())).toEqual({
      nome: "Paciente Fictício Copmed",
      idade: "38 anos e 2 meses",
      sexo: "Feminino",
    });
  });

  it("lê as seções preenchidas do SOAP, uma linha por bloco do Draft.js", () => {
    const page = criarPaginaPec({ textos: { O: "PA 120/80 mmHg.\nAfebril.", P: "Retorno em 7 dias." } });
    expect(adaptador.readClinicalNotes(page)).toEqual({
      objetivo: "PA 120/80 mmHg.\nAfebril.",
      plano: "Retorno em 7 dias.",
    });
  });

  it("não confunde o placeholder do editor com texto", () => {
    expect(adaptador.readClinicalNotes(criarPaginaPec({ textos: {} }))).toBeNull();
  });

  it("escreve cada seção no seu campo", async () => {
    const page = criarPaginaPec({ textos: {} });

    expect(await adaptador.writeEvolution(SOAP, page)).toEqual({ ok: true });
    expect(adaptador.readClinicalNotes(page)).toEqual(separarSecoesSoap(SOAP));
  });

  it("acrescenta ao que o médico já escreveu, sem apagar", async () => {
    const page = criarPaginaPec({ textos: { O: "PA 120/80 mmHg." } });

    await adaptador.writeEvolution("Objetivo: Afebril.", page);

    expect(adaptador.readClinicalNotes(page)?.objetivo).toBe("PA 120/80 mmHg.\n\nAfebril.");
  });

  it("falha sem escrever se o Draft.js não tratar a colagem", async () => {
    const page = criarPaginaPec({ textos: {}, semDraft: true });

    expect(await adaptador.writeEvolution(SOAP, page)).toEqual({ ok: false, motivo: "falha_ao_escrever" });
    expect(adaptador.readClinicalNotes(page)).toBeNull();
  });

  it("não escreve nada se faltar o campo de alguma seção", async () => {
    const page = criarPaginaPec({ textos: {} });
    page.querySelector('[data-testid="textFieldPlano"]')?.remove();

    expect(await adaptador.writeEvolution(SOAP, page)).toEqual({ ok: false, motivo: "campo_nao_encontrado" });
    expect(adaptador.readClinicalNotes(page)).toBeNull();
  });

  it("recusa seção acima do limite de caracteres do PEC sem escrever nada", async () => {
    const page = criarPaginaPec({ textos: {} });
    const longo = `Subjetivo: ok.\nPlano: ${"x".repeat(LIMITE_CARACTERES_CAMPO + 1)}`;

    expect(await adaptador.writeEvolution(longo, page)).toEqual({ ok: false, motivo: "falha_ao_escrever" });
    expect(adaptador.readClinicalNotes(page)).toBeNull();
  });

  it("não detecta páginas fora do atendimento", () => {
    const page = new DOMParser().parseFromString(
      "<html><body><header><h2>Lista de atendimentos</h2></header></body></html>",
      "text/html",
    );
    expect(adaptador.detect(page)).toBe(false);
    expect(adaptador.readPatient(page)).toBeNull();
  });
});
