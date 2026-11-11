// @vitest-environment jsdom
/**
 * Roda a suíte de contrato do PepAdapter contra o adaptador do Amplimed
 * (B49), usando a fixture da tela de consulta. O Amplimed ainda não lê o
 * cabeçalho do paciente: a suíte exige `null` em vez de dados inventados.
 */

import { criarAmplimedAdapter } from "./amplimed";
import { rodarSuiteDeContratoPepAdapter } from "../test/pepAdapterContract";
import fixture from "../../tests/fixtures/pep/amplimed-consulta.html?raw";

rodarSuiteDeContratoPepAdapter({
  nome: "AmplimedAdapter",
  criarAdaptador: criarAmplimedAdapter,
  criarPaginaPep: () => new DOMParser().parseFromString(fixture, "text/html"),
  lerCampoEvolucao: (page) =>
    page.querySelector<HTMLTextAreaElement>('textarea[f_prontuario="evolucao"]')?.value ?? null,
  lePaciente: false,
});
