/**
 * Fixtures HTML dos PEPs (B54): os arquivos de `tests/fixtures/pep/`, carregados como texto.
 *
 * `import.meta.glob` (e não um import por arquivo) para o helper não quebrar enquanto um
 * arquivo ainda não existe: quem pede uma fixture ausente recebe um erro com o nome dela.
 */

import { simularDraft } from "./esusPecPagina";

const brutos = import.meta.glob<string>("../../tests/fixtures/pep/*.html", {
  query: "?raw",
  import: "default",
  eager: true,
});

export const FIXTURES_PEP = {
  amplimedConsulta: "amplimed-consulta.html",
  esusPecSoapVazio: "esus-pec-soap-vazio.html",
  esusPecSoapPreenchido: "esus-pec-soap-preenchido.html",
  esusPecListaAtendimentos: "esus-pec-lista-atendimentos.html",
  paginaGenerica: "pagina-generica.html",
} as const;

/** Textos da fixture "preenchida" do e-SUS PEC; os testes do adaptador leem estes mesmos valores. */
export const TEXTOS_PEC_PREENCHIDO = {
  S: "Tosse seca há três dias.\nNega febre.",
  O: "PA 120/80 mmHg.\nAfebril.",
};

export type NomeFixturePep = (typeof FIXTURES_PEP)[keyof typeof FIXTURES_PEP];

/** HTML bruto da fixture, com fim de linha normalizado (no Windows o checkout pode trazer CRLF). */
export function htmlFixture(nome: NomeFixturePep): string {
  const caminho = Object.keys(brutos).find((chave) => chave.endsWith(`/${nome}`));
  if (!caminho) throw new Error(`Fixture ${nome} não encontrada em tests/fixtures/pep/.`);
  return brutos[caminho].replace(/\r\n/g, "\n");
}

/** Documento novo a cada chamada: um teste nunca enxerga o que outro alterou. */
export function documentoDe(nome: NomeFixturePep): Document {
  return new DOMParser().parseFromString(htmlFixture(nome), "text/html");
}

/** Tela do e-SUS PEC com o Draft.js simulado (a colagem é tratada), ou recusando-a com `semDraft`. */
export function paginaPecDe(nome: NomeFixturePep, { semDraft = false } = {}): Document {
  const page = documentoDe(nome);
  if (!semDraft) simularDraft(page);
  return page;
}
