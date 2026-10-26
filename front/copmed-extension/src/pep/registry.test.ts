// @vitest-environment jsdom
/**
 * Testes do registry de adaptadores de PEP (B48).
 *
 * Cada teste cria uma instância nova via `createPepRegistry()` — sem
 * compartilhar estado com outros testes. O adaptador usado aqui é um
 * fake local, mínimo, com o único propósito de exercitar o registry.
 * O fake reutilizável para a suíte de contrato mora em src/test/.
 */

import { describe, expect, it } from "vitest";
import type { PepAdapter, WriteEvolutionResult } from "./pepAdapter";
import { createPepRegistry } from "./registry";

/**
 * Cria um adaptador fake que devolve sempre o mesmo resultado de
 * `detect` e nada nos métodos de leitura. Usado para exercitar o
 * registry sem depender de DOM.
 */
function criarAdaptadorFake(
  id: string,
  detecta: boolean = false,
): PepAdapter {
  return {
    id,
    detect: () => detecta,
    readPatient: () => null,
    readClinicalNotes: () => null,
    writeEvolution: async (): Promise<WriteEvolutionResult> => ({ ok: true }),
  };
}

/**
 * Cria um adaptador fake cujo `detect` sempre lança. Serve para verificar
 * que uma falha isolada de adaptador não derruba o registry inteiro.
 */
function criarAdaptadorQueLancaNoDetect(id: string): PepAdapter {
  return {
    id,
    detect: () => {
      throw new Error("Erro simulado no detect.");
    },
    readPatient: () => null,
    readClinicalNotes: () => null,
    writeEvolution: async (): Promise<WriteEvolutionResult> => ({ ok: true }),
  };
}

describe("createPepRegistry — cadastro e consulta", () => {
  it("cadastra um adaptador e o devolve em list()", () => {
    const registro = createPepRegistry();
    const adaptador = criarAdaptadorFake("pep-teste");

    registro.register(adaptador);

    expect(registro.list()).toEqual([adaptador]);
  });

  it("get devolve o adaptador pelo id", () => {
    const registro = createPepRegistry();
    const adaptador = criarAdaptadorFake("amplimed");

    registro.register(adaptador);

    expect(registro.get("amplimed")).toBe(adaptador);
  });

  it("get devolve undefined para id não cadastrado", () => {
    const registro = createPepRegistry();

    expect(registro.get("inexistente")).toBeUndefined();
  });

  it("rejeita cadastro com id duplicado", () => {
    const registro = createPepRegistry();
    registro.register(criarAdaptadorFake("amplimed"));

    expect(() => registro.register(criarAdaptadorFake("amplimed"))).toThrow(
      /já existe um adaptador/i,
    );
  });

  it("rejeita id vazio", () => {
    const registro = createPepRegistry();

    expect(() => registro.register(criarAdaptadorFake(""))).toThrow(
      /texto não vazio/i,
    );
  });

  it("rejeita id com maiúsculas, espaço ou símbolo", () => {
    const registro = createPepRegistry();
    const idsInvalidos = ["Amplimed", "esus pec", "esus_pec", "pep!"];

    for (const idInvalido of idsInvalidos) {
      expect(() =>
        registro.register(criarAdaptadorFake(idInvalido)),
      ).toThrow(/id de adaptador inválido/i);
    }
  });

  it("alterar o array devolvido por list() não afeta o registro interno", () => {
    const registro = createPepRegistry();
    const adaptador = criarAdaptadorFake("pep-teste");
    registro.register(adaptador);

    const listaExterna = registro.list();
    listaExterna.push(criarAdaptadorFake("outro"));

    expect(registro.list()).toEqual([adaptador]);
  });
});

describe("createPepRegistry — detect", () => {
  it("detect devolve o adaptador cujo detect deu true", () => {
    const registro = createPepRegistry();
    const naoDetecta = criarAdaptadorFake("pep-a", false);
    const detecta = criarAdaptadorFake("pep-b", true);
    registro.register(naoDetecta);
    registro.register(detecta);

    expect(registro.detect()).toBe(detecta);
  });

  it("detect devolve null quando nenhum adaptador casa", () => {
    const registro = createPepRegistry();
    registro.register(criarAdaptadorFake("pep-a", false));
    registro.register(criarAdaptadorFake("pep-b", false));

    expect(registro.detect()).toBeNull();
  });

  it("empate: devolve o primeiro adaptador cadastrado", () => {
    const registro = createPepRegistry();
    const primeiro = criarAdaptadorFake("pep-primeiro", true);
    const segundo = criarAdaptadorFake("pep-segundo", true);
    registro.register(primeiro);
    registro.register(segundo);

    expect(registro.detect()).toBe(primeiro);
  });

  it("detect de um adaptador que lança erro não impede os demais", () => {
    const registro = createPepRegistry();
    registro.register(criarAdaptadorQueLancaNoDetect("pep-quebrado"));
    const saudavel = criarAdaptadorFake("pep-saudavel", true);
    registro.register(saudavel);

    expect(registro.detect()).toBe(saudavel);
  });

  it("se o único adaptador lançar erro, detect devolve null", () => {
    const registro = createPepRegistry();
    registro.register(criarAdaptadorQueLancaNoDetect("pep-quebrado"));

    expect(registro.detect()).toBeNull();
  });
});

describe("createPepRegistry — isolamento entre instâncias", () => {
  it("duas instâncias não compartilham adaptadores", () => {
    const registroA = createPepRegistry();
    const registroB = createPepRegistry();
    registroA.register(criarAdaptadorFake("pep-a"));

    expect(registroA.list()).toHaveLength(1);
    expect(registroB.list()).toHaveLength(0);
    expect(registroB.get("pep-a")).toBeUndefined();
  });
});
