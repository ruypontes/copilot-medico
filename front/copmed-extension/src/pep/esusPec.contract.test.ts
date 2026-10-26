// @vitest-environment jsdom
/**
 * Roda a suíte de contrato do PepAdapter contra o adaptador do e-SUS PEC
 * (B50), usando a página fictícia que imita a aba SOAP do PEC 5.5.28.
 */

import { criarEsusPecAdapter } from "./esusPec";
import { criarPaginaPec, lerSubjetivoPec } from "../test/esusPecPagina";
import { rodarSuiteDeContratoPepAdapter } from "../test/pepAdapterContract";

rodarSuiteDeContratoPepAdapter({
  nome: "EsusPecAdapter",
  criarAdaptador: criarEsusPecAdapter,
  criarPaginaPep: () => criarPaginaPec(),
  lerCampoEvolucao: lerSubjetivoPec,
});
