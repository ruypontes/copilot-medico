// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import fixtureAmplimed from "../../tests/fixtures/pep/amplimed-consulta.html?raw";
import { pepRegistry } from "../pep/registry";
import { criarPaginaPec } from "../test/esusPecPagina";
import { ehComandoPep, tratarComandoPep } from "./comandosPep";

// B53: o popup pergunta o PEP da aba e pede a escrita; frame sem PEP não responde.

describe("comandos do popup ao content script", () => {
  it("reconhece só os comandos do contrato", () => {
    expect(ehComandoPep({ type: "pep:status" })).toBe(true);
    expect(ehComandoPep({ type: "pep:write", text: "Subjetivo: x" })).toBe(true);
    expect(ehComandoPep({ type: "pep:write" })).toBe(false);
    expect(ehComandoPep({ type: "SEND_COMBINED_DATA" })).toBe(false);
    expect(ehComandoPep(null)).toBe(false);
  });

  it("status devolve o PEP detectado e o paciente do cabeçalho, ou null fora de PEP", async () => {
    expect(await tratarComandoPep({ type: "pep:status" }, pepRegistry, criarPaginaPec())).toEqual({
      pep: "esus-pec",
      paciente: { nome: "Paciente Fictício Copmed", sexo: "Feminino", idade: "38 anos e 2 meses" },
    });
    document.body.innerHTML = fixtureAmplimed;
    expect(await tratarComandoPep({ type: "pep:status" }, pepRegistry, document)).toEqual({
      pep: "amplimed",
      paciente: null,
    });
    document.body.innerHTML = "<p>outro site</p>";
    expect(await tratarComandoPep({ type: "pep:status" }, pepRegistry, document)).toBeNull();
  });

  it("escrita vai pelo adaptador do PEP da página", async () => {
    const page = criarPaginaPec();
    const resposta = await tratarComandoPep(
      { type: "pep:write", text: "Subjetivo: Tosse há 3 dias.\nPlano: Retorno em 7 dias." },
      pepRegistry,
      page,
    );
    expect(resposta).toEqual({ pep: "esus-pec", resultado: { ok: true } });
    expect(page.querySelector("[data-testid='textFieldPlano']")?.textContent).toContain("Retorno em 7 dias.");
  });

  it("fora de PEP nada é escrito", async () => {
    document.body.innerHTML = "<textarea id='campo'></textarea>";
    expect(await tratarComandoPep({ type: "pep:write", text: "Plano: x" }, pepRegistry, document)).toBeNull();
    expect((document.getElementById("campo") as HTMLTextAreaElement).value).toBe("");
  });
});
