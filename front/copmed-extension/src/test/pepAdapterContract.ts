/**
 * Suíte de contrato reutilizável para adaptadores de PEP (B48).
 *
 * Este arquivo NÃO é um teste que roda sozinho. Ele exporta a função
 * `rodarSuiteDeContratoPepAdapter`, que registra os `describe`/`it` no
 * contexto de quem a chamar. Assim:
 *   - `pepAdapter.contract.test.ts` roda contra o fake (B48, agora).
 *   - `amplimed.contract.test.ts` roda contra o Amplimed (B49).
 *   - `esusPec.contract.test.ts` roda contra o e-SUS PEC (B50).
 *
 * O nome do arquivo NÃO termina em `.test.ts` de propósito: se
 * terminasse, o Vitest tentaria executá-lo diretamente e falharia por
 * falta dos parâmetros obrigatórios.
 */

import { describe, expect, it } from "vitest";
import type { PepAdapter } from "../pep/pepAdapter";

/**
 * Opções aceitas pela suíte de contrato.
 *
 * - `nome`: rótulo do adaptador (aparece no `describe`).
 * - `criarAdaptador`: FÁBRICA de adaptador. Cada teste recebe uma
 *   instância nova, para um teste não contaminar o outro.
 * - `criarPaginaPep`: FÁBRICA da página "do PEP" (um `Document`). Cada
 *   teste recebe uma página nova, sem estado herdado.
 * - `lerCampoEvolucao`: OPCIONAL. Quando fornecida, a suíte verifica
 *   que o texto escrito por `writeEvolution` aparece de fato no campo
 *   de evolução da página.
 * - `lePaciente`: OPCIONAL (padrão true). `false` para um adaptador que
 *   ainda não lê o cabeçalho do paciente: a suíte passa a exigir `null`
 *   na página do PEP, em vez de dados inventados.
 */
export interface OpcoesContratoPepAdapter {
  nome: string;
  criarAdaptador: () => PepAdapter;
  criarPaginaPep: () => Document;
  lerCampoEvolucao?: (page: Document) => string | null;
  lePaciente?: boolean;
}

/**
 * Padrão de id do contrato: apenas minúsculas, números e hífen. É o
 * mesmo padrão exigido pelo registry. Duplicado aqui de propósito: o
 * teste de contrato do adaptador precisa garantir o formato do id sem
 * depender de detalhe interno do registry.
 */
const PADRAO_ID_CONTRATO = /^[a-z0-9-]+$/;

/**
 * Cria uma página vazia (sem elementos) para os testes que verificam
 * comportamento "na ausência do PEP". Cada chamada devolve um `Document`
 * novo, para evitar contaminação entre testes.
 */
function criarPaginaVazia(): Document {
  const parser = new DOMParser();
  return parser.parseFromString("<html><body></body></html>", "text/html");
}

/**
 * Registra a suíte de contrato para um adaptador. A função é síncrona
 * do ponto de vista de quem chama: ela registra `describe`/`it` e
 * retorna. Os testes em si rodam de forma assíncrona quando o Vitest
 * chegar neles.
 */
export function rodarSuiteDeContratoPepAdapter(
  opcoes: OpcoesContratoPepAdapter,
): void {
  const { nome, criarAdaptador, criarPaginaPep, lerCampoEvolucao, lePaciente = true } = opcoes;

  describe(`Contrato do adaptador de PEP: ${nome}`, () => {
    // -----------------------------------------------------------------
    // id
    // -----------------------------------------------------------------
    it("expõe um id não vazio no formato minúsculas/números/hífen", () => {
      const adaptador = criarAdaptador();
      expect(typeof adaptador.id).toBe("string");
      expect(adaptador.id.length).toBeGreaterThan(0);
      expect(adaptador.id).toMatch(PADRAO_ID_CONTRATO);
    });

    // -----------------------------------------------------------------
    // detect
    // -----------------------------------------------------------------
    it("detect devolve false em uma página vazia", () => {
      const adaptador = criarAdaptador();
      expect(adaptador.detect(criarPaginaVazia())).toBe(false);
    });

    it("detect devolve true na página do PEP", () => {
      const adaptador = criarAdaptador();
      expect(adaptador.detect(criarPaginaPep())).toBe(true);
    });

    it("detect não lança em página vazia", () => {
      const adaptador = criarAdaptador();
      expect(() => adaptador.detect(criarPaginaVazia())).not.toThrow();
    });

    // -----------------------------------------------------------------
    // readPatient
    // -----------------------------------------------------------------
    it("readPatient devolve null em página vazia", () => {
      const adaptador = criarAdaptador();
      expect(adaptador.readPatient(criarPaginaVazia())).toBeNull();
    });

    it("readPatient na página do PEP só tem chaves nome/idade/sexo e todas são texto", () => {
      const adaptador = criarAdaptador();
      const resultado = adaptador.readPatient(criarPaginaPep());

      if (!lePaciente) {
        expect(resultado).toBeNull();
        return;
      }

      expect(resultado).not.toBeNull();
      if (resultado === null) return; // apenas para estreitar o tipo

      const chavesPermitidas = new Set(["nome", "idade", "sexo"]);
      for (const chave of Object.keys(resultado)) {
        expect(chavesPermitidas.has(chave)).toBe(true);
      }
      for (const valor of Object.values(resultado)) {
        expect(typeof valor).toBe("string");
      }
    });

    // -----------------------------------------------------------------
    // readClinicalNotes
    // -----------------------------------------------------------------
    it("readClinicalNotes devolve null em página vazia", () => {
      const adaptador = criarAdaptador();
      expect(adaptador.readClinicalNotes(criarPaginaVazia())).toBeNull();
    });

    it("readClinicalNotes na página do PEP devolve valores texto não vazios e sem espaços nas pontas", () => {
      const adaptador = criarAdaptador();
      const resultado = adaptador.readClinicalNotes(criarPaginaPep());

      expect(resultado).not.toBeNull();
      if (resultado === null) return;

      const entradas = Object.entries(resultado);
      expect(entradas.length).toBeGreaterThan(0);

      for (const [, valor] of entradas) {
        expect(typeof valor).toBe("string");
        expect(valor.length).toBeGreaterThan(0);
        expect(valor).toBe(valor.trim());
      }
    });

    // -----------------------------------------------------------------
    // writeEvolution
    // -----------------------------------------------------------------
    it("writeEvolution com texto vazio devolve ok:false e motivo texto_vazio", async () => {
      const adaptador = criarAdaptador();
      const resultado = await adaptador.writeEvolution(
        "",
        criarPaginaPep(),
      );

      expect(resultado.ok).toBe(false);
      if (!resultado.ok) {
        expect(resultado.motivo).toBe("texto_vazio");
      }
    });

    it("writeEvolution em página vazia devolve ok:false e motivo campo_nao_encontrado", async () => {
      const adaptador = criarAdaptador();
      const resultado = await adaptador.writeEvolution(
        "Evolução em página sem campo.",
        criarPaginaVazia(),
      );

      expect(resultado.ok).toBe(false);
      if (!resultado.ok) {
        expect(resultado.motivo).toBe("campo_nao_encontrado");
      }
    });

    it("writeEvolution com texto na página do PEP devolve ok:true", async () => {
      const adaptador = criarAdaptador();
      const pagina = criarPaginaPep();
      const texto = "Evolução escrita pelo teste de contrato (texto fictício).";

      const resultado = await adaptador.writeEvolution(texto, pagina);
      expect(resultado.ok).toBe(true);

      // Só faz sentido inspecionar o campo se o adaptador declarou
      // como lê-lo. Sem a opção, o contrato para por aqui.
      if (lerCampoEvolucao) {
        expect(lerCampoEvolucao(pagina)).toBe(texto);
      }
    });
  });
}
