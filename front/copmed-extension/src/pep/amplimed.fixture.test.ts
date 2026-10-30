// @vitest-environment jsdom
/**
 * AmplimedAdapter sobre as fixtures HTML (B54).
 *
 * `amplimed.test.ts` (B52) cobre a extração completa, a detecção e a escrita ainda pendente.
 * Aqui entram as variações de página que o médico encontra de verdade (só sinais vitais, só notas,
 * espaços sobrando) e a lista do que a B49 ainda vai entregar, como `it.todo`.
 *
 * Todos os testes passam a página por parâmetro (DOMParser): o `document` global fica vazio.
 */

import { describe, expect, it } from "vitest";
import { FIXTURES_PEP, documentoDe } from "../test/fixturesPep";
import { amplimedAdapter } from "./amplimed";

const { amplimedConsulta, paginaGenerica } = FIXTURES_PEP;

// Valores de tests/fixtures/pep/amplimed-consulta.html.
const VITAIS = { peso: "72.5", altura: "1.68", imc: "25.7", tempe: "37.8", freqres: "18", freqcar: "88", pas: "120", pad: "80" };
const NOTAS = {
  anamnese: "Paciente relata febre há 3 dias com tosse seca e dor de garganta.",
  exame_fisico: "Sem sinais de desidratação, murmúrio vesicular presente e sem roncos.",
  conclusao_diagnostica: "Quadro compatível com virose, manter hidratação e observação.",
  lista_problemas: "Febre, tosse, dor de garganta.",
};

function notasDe(doc: Document): HTMLElement[] {
  return [...doc.querySelectorAll<HTMLElement>(".note-editable")];
}

describe("leitura da consulta", () => {
  it("lê os oito sinais vitais e as quatro notas, sem tocar no document global", () => {
    expect(document.body.innerHTML).toBe("");

    const dados = amplimedAdapter.readClinicalNotes(documentoDe(amplimedConsulta));

    expect(dados).toMatchObject({ ...VITAIS });
    expect(Object.keys(dados ?? {}).sort()).toEqual([...Object.keys(VITAIS), ...Object.keys(NOTAS)].sort());
  });

  it("página só com sinais vitais: devolve só os oito", () => {
    const doc = documentoDe(amplimedConsulta);
    notasDe(doc).forEach((nota) => nota.remove());

    expect(amplimedAdapter.readClinicalNotes(doc)).toEqual(VITAIS);
    expect(amplimedAdapter.detect(doc), "os campos f_prontuario bastam para detectar").toBe(true);
  });

  it("página só com notas: devolve só as quatro", () => {
    const doc = documentoDe(amplimedConsulta);
    doc.querySelectorAll("[f_prontuario]").forEach((campo) => campo.remove());

    expect(amplimedAdapter.readClinicalNotes(doc)).toMatchObject(NOTAS);
    expect(Object.keys(amplimedAdapter.readClinicalNotes(doc) ?? {})).toHaveLength(4);
    expect(amplimedAdapter.detect(doc), "as caixas de texto do prontuário bastam para detectar").toBe(true);
  });

  it("tira os espaços das pontas dos valores e das notas", () => {
    const doc = documentoDe(amplimedConsulta);
    doc.querySelector<HTMLInputElement>('input[f_prontuario="peso"]')!.value = "  72,5 ";
    notasDe(doc)[0].textContent = "\n  Tosse seca.  \n";

    const dados = amplimedAdapter.readClinicalNotes(doc);

    expect(dados?.peso).toBe("72,5");
    expect(dados?.anamnese).toBe("Tosse seca.");
  });

  it("sinal vital em branco é ignorado; os outros continuam", () => {
    const doc = documentoDe(amplimedConsulta);
    doc.querySelector<HTMLInputElement>('input[f_prontuario="peso"]')!.value = "   ";

    const dados = amplimedAdapter.readClinicalNotes(doc);

    expect(dados).not.toHaveProperty("peso");
    expect(dados).toMatchObject({ altura: VITAIS.altura, pas: VITAIS.pas });
  });

  it("nota só com espaços é ignorada; as outras continuam", () => {
    const doc = documentoDe(amplimedConsulta);
    notasDe(doc)[1].textContent = "   \n ";

    const dados = amplimedAdapter.readClinicalNotes(doc);

    expect(dados).not.toHaveProperty("exame_fisico");
    expect(dados).toMatchObject({ anamnese: NOTAS.anamnese, conclusao_diagnostica: NOTAS.conclusao_diagnostica });
  });

  /**
   * LIMITAÇÃO CONHECIDA, documentada de propósito: o NOME da nota vem da POSIÇÃO dela na página
   * (a 1ª caixa é a anamnese, a 2ª o exame físico...), não de um rótulo. Se uma caixa sumir ou a
   * ordem mudar, as outras ficam com o nome trocado e ninguém é avisado. Se a B49 passar a
   * identificar a nota por rótulo, este teste deve ser atualizado, e isso é bom.
   */
  it("limitação conhecida: o nome da nota vem da posição na página", () => {
    const doc = documentoDe(amplimedConsulta);
    notasDe(doc)[0].remove(); // some a anamnese

    const dados = amplimedAdapter.readClinicalNotes(doc);

    expect(dados?.anamnese, "o exame físico passou a se chamar anamnese").toBe(NOTAS.exame_fisico);
    expect(dados?.exame_fisico, "a conclusão passou a se chamar exame_fisico").toBe(NOTAS.conclusao_diagnostica);
    expect(dados).not.toHaveProperty("lista_problemas");
  });
});

describe("páginas que não são o prontuário do Amplimed", () => {
  it("a página genérica (com textarea e editor contenteditable) não é lida", () => {
    const doc = documentoDe(paginaGenerica);

    expect(amplimedAdapter.detect(doc)).toBe(false);
    expect(amplimedAdapter.readClinicalNotes(doc)).toBeNull();
  });

  it("identifica-se como amplimed", () => {
    expect(amplimedAdapter.id).toBe("amplimed");
  });
});

/** O que a B49 (leitura do cabeçalho e escrita da evolução no Amplimed) ainda precisa entregar. */
describe("pendente da B49", () => {
  it.todo("readPatient: lê nome, idade e sexo do cabeçalho do Amplimed (hoje devolve null)");
  it.todo("writeEvolution: escreve a evolução no campo do prontuário (hoje devolve campo_nao_encontrado)");
  it.todo("fixture com o campo de evolução do Amplimed (o DOM real precisa ser capturado do sistema)");
  it.todo("passar na suíte de contrato: criar amplimed.contract.test.ts com rodarSuiteDeContratoPepAdapter");
  it.todo("formatSoapForPep específico do Amplimed, se o campo dele exigir outro formato");
});
