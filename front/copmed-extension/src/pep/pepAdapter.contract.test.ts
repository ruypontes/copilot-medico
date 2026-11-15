// @vitest-environment jsdom
/**
 * Roda a suíte de contrato do PepAdapter contra o adaptador FAKE (B48).
 *
 * Este arquivo é o "cliente" da suíte reutilizável: ele não define
 * nenhum teste próprio — apenas chama `rodarSuiteDeContratoPepAdapter`
 * passando as fábricas do fake. B49 (Amplimed) e B50 (e-SUS PEC) têm
 * arquivos equivalentes a este (amplimed.contract.test.ts e
 * esusPec.contract.test.ts). Os testes em si moram em `pepAdapterContract.ts`.
 *
 * Critério de aceite da B48: "Adaptador falso passa nos testes de
 * interface" — é exatamente o que este arquivo comprova.
 */

import { criarFakePepAdapter, criarPaginaPepFake, lerCampoEvolucaoFake } from "../test/fakePepAdapter";
import { rodarSuiteDeContratoPepAdapter } from "../test/pepAdapterContract";

rodarSuiteDeContratoPepAdapter({
  nome: "FakePepAdapter",
  criarAdaptador: criarFakePepAdapter,
  criarPaginaPep: criarPaginaPepFake,
  lerCampoEvolucao: lerCampoEvolucaoFake,
});