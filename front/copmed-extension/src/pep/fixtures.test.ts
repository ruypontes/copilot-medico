// @vitest-environment jsdom
/// <reference types="node" />
/**
 * Fixtures HTML dos PEPs (B54): elas existem, estão em dia com a fonte e cada adaptador só
 * reconhece as suas.
 *
 * O HTML do e-SUS PEC tem UMA fonte, `htmlPaginaPec` (`src/test/esusPecPagina.ts`), que 6
 * arquivos de teste e o E2E já usam. Os `.html` de `tests/fixtures/pep/` derivados dela existem
 * para serem abertos e lidos por humanos (e no navegador), e este teste acusa se divergirem.
 * As demais (Amplimed, página genérica, lista de atendimentos) são escritas à mão e são a fonte
 * delas mesmas. Veja `tests/fixtures/pep/README.md`.
 *
 * Para regenerar as derivadas depois de mudar `htmlPaginaPec`:
 *   ATUALIZAR_FIXTURES=1 npx vitest run src/pep/fixtures.test.ts      (e rode de novo, sem a variável)
 */

import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { htmlPaginaPec } from "../test/esusPecPagina";
import { FIXTURES_PEP, TEXTOS_PEC_PREENCHIDO, documentoDe, htmlFixture, type NomeFixturePep } from "../test/fixturesPep";
import { amplimedAdapter } from "./amplimed";
import { esusPecAdapter } from "./esusPec";
import { pepRegistry } from "./registry";

const DERIVADAS_DO_HTMLPAGINAPEC: Partial<Record<NomeFixturePep, string>> = {
  [FIXTURES_PEP.esusPecSoapVazio]: htmlPaginaPec({ textos: {} }),
  [FIXTURES_PEP.esusPecSoapPreenchido]: htmlPaginaPec({ textos: TEXTOS_PEC_PREENCHIDO }),
};

// Sem `new URL(..., import.meta.url)`: o plugin de assets do Vite reescreve esse padrao (o arquivo
// era "gravado" em outro lugar, sem erro). dirname + resolve nao sofrem essa transformacao.
const PASTA_FIXTURES = resolve(dirname(fileURLToPath(import.meta.url)), "../../tests/fixtures/pep");

const aparar = (html: string) => html.replace(/\r\n/g, "\n").trimEnd();

const ATUALIZANDO = process.env.ATUALIZAR_FIXTURES === "1";
// Na execução de atualização as fixtures ainda não estão carregadas (o Vite as lê antes de o
// teste gravar), então as verificações só rodam na execução seguinte.
const verificar = ATUALIZANDO ? describe.skip : describe;

if (ATUALIZANDO) {
  describe("atualização das fixtures derivadas", () => {
    it("grava os arquivos (rode de novo SEM ATUALIZAR_FIXTURES para validar)", () => {
      for (const [nome, html] of Object.entries(DERIVADAS_DO_HTMLPAGINAPEC)) {
        writeFileSync(resolve(PASTA_FIXTURES, nome), `${html}\n`);
      }
    });
  });
}

verificar("fixtures do e-SUS PEC derivadas de htmlPaginaPec", () => {
  it.each(Object.entries(DERIVADAS_DO_HTMLPAGINAPEC))("%s está em dia com htmlPaginaPec", (nome, esperado) => {
    const emDisco = aparar(htmlFixture(nome as NomeFixturePep));
    // Sem toBe em um HTML inteiro: a falha seria ilegível. A dica de regeneração é o que importa.
    expect(
      emDisco === aparar(esperado!),
      `tests/fixtures/pep/${nome} divergiu de htmlPaginaPec. Regenere com: ATUALIZAR_FIXTURES=1 npx vitest run src/pep/fixtures.test.ts`,
    ).toBe(true);
  });
});

verificar("todas as fixtures existem e são HTML de verdade", () => {
  it.each(Object.values(FIXTURES_PEP))("%s", (nome) => {
    const doc = documentoDe(nome);
    expect(doc.body, "a fixture deve ter <body>").not.toBeNull();
    expect(htmlFixture(nome).length).toBeGreaterThan(100);
  });

  it("os parses são independentes: o que um teste altera não aparece no seguinte", () => {
    const primeiro = documentoDe(FIXTURES_PEP.esusPecSoapVazio);
    primeiro.body.innerHTML = "";
    expect(documentoDe(FIXTURES_PEP.esusPecSoapVazio).body.innerHTML.length).toBeGreaterThan(100);
  });
});

/**
 * Cada fixture é reconhecida pelo adaptador certo e SÓ por ele; o registry devolve o mesmo.
 * É a garantia de que o botão da extensão aparece no PEP certo e em nenhuma outra página.
 */
verificar("detecção: fixtures × adaptadores", () => {
  const MATRIZ: [NomeFixturePep, { amplimed: boolean; esusPec: boolean; registry: string | null }][] = [
    [FIXTURES_PEP.amplimedConsulta, { amplimed: true, esusPec: false, registry: "amplimed" }],
    [FIXTURES_PEP.esusPecSoapVazio, { amplimed: false, esusPec: true, registry: "esus-pec" }],
    [FIXTURES_PEP.esusPecSoapPreenchido, { amplimed: false, esusPec: true, registry: "esus-pec" }],
    [FIXTURES_PEP.esusPecListaAtendimentos, { amplimed: false, esusPec: false, registry: null }],
    [FIXTURES_PEP.paginaGenerica, { amplimed: false, esusPec: false, registry: null }],
  ];

  it.each(MATRIZ)("%s", (nome, esperado) => {
    const page = documentoDe(nome);

    expect(amplimedAdapter.detect(page), "Amplimed").toBe(esperado.amplimed);
    expect(esusPecAdapter.detect(page), "e-SUS PEC").toBe(esperado.esusPec);
    expect(pepRegistry.detect(page)?.id ?? null, "registry").toBe(esperado.registry);
  });

  it("nenhuma fixture é reconhecida por dois adaptadores ao mesmo tempo", () => {
    for (const nome of Object.values(FIXTURES_PEP)) {
      const page = documentoDe(nome);
      const quantos = [amplimedAdapter, esusPecAdapter].filter((adaptador) => adaptador.detect(page)).length;
      expect(quantos, nome).toBeLessThanOrEqual(1);
    }
  });
});
