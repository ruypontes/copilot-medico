/**
 * E2E do cenário feliz (B56 / docs/09): no Chromium com a extensão, a médica entra,
 * cria o paciente, grava a consulta com o áudio de fixture, o SOAP é gerado (IA de
 * fixture) e aprovado, e o SOAP vai para o atendimento do e-SUS PEC aberto na aba.
 *
 * Login, paciente e gravação são clicados no popup de verdade. O SOAP ainda não tem
 * tela no popup (SoapEditor, B43): gerar, aprovar e inserir seguem a mesma sequência
 * do botão "Inserir no prontuário" (InsertIntoPepButton.tsx), feita de dentro do popup.
 * Quando o B43 entrar, esses passos viram cliques.
 *
 * Amplimed fica de fora: não há Amplimed falso; a escrita dele (B49) é coberta por
 * src/pep/amplimed.test.ts e amplimed.contract.test.ts.
 */

import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { ComandoPep, RespostaEscritaPep, RespostaStatusPep } from "../src/content/comandosPep";
import type { SoapDocument } from "../src/features/shared/types";
import { conferirPaciente } from "../src/pep/conferirPaciente";
import { formatSoapForPep } from "../src/pep/formatarSoap";
import { Navegador } from "./navegador";
import { abrirPecFalso, textoDaSecao } from "./pecFalso";

const fixture = JSON.parse(
  readFileSync(new URL("./fixtures/consulta-infeccao-respiratoria.json", import.meta.url), "utf8"),
);
const AUDIO = fileURLToPath(new URL(`../../../${fixture.audio}`, import.meta.url));

type RespostaApi = { status: number; dados: { soap: SoapDocument } };

/** Chama a API de dentro do popup, com a sessão que o login guardou (como o services/api.ts). */
function chamarApi(popup: Page, metodo: string, caminho: string, corpo?: unknown): Promise<RespostaApi> {
  return popup.evaluate(
    async ({ metodo, caminho, corpo }) => {
      const { copmed_extension_token: token } = await chrome.storage.session.get("copmed_extension_token");
      const { copmed_api_url: api } = await chrome.storage.local.get("copmed_api_url");
      const resposta = await fetch(`${api}${caminho}`, {
        method: metodo,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: corpo === undefined ? undefined : JSON.stringify(corpo),
      });
      return { status: resposta.status, dados: await resposta.json() };
    },
    { metodo, caminho, corpo },
  );
}

/** Comando ao content script da aba ativa, como a ponte do popup (src/features/soap/pepDaAba.ts). */
function comandoAoPep<T>(popup: Page, comando: ComandoPep): Promise<T | null> {
  return popup.evaluate(async (comando) => {
    const [aba] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (aba?.id === undefined) return null;
    return (await chrome.tabs.sendMessage(aba.id, comando)) ?? null;
  }, comando);
}

let navegador: Navegador;
let popup: Page | undefined;

test.beforeAll(async () => {
  navegador = await Navegador.abrir(AUDIO);
});

test.afterEach(async () => {
  const testInfo = test.info();
  if (testInfo.status === testInfo.expectedStatus) return;
  for (const pagina of [popup, navegador.contexto.pages()[0]]) {
    if (pagina && !pagina.isClosed()) {
      await testInfo.attach(`falha-${pagina === popup ? "popup" : "pec"}`, {
        body: await pagina.screenshot(),
        contentType: "image/png",
      });
    }
  }
});

test.afterAll(async () => {
  await navegador?.fechar();
});

test("cenário feliz no e-SUS PEC", async () => {
  const pec = navegador.contexto.pages()[0] ?? (await navegador.contexto.newPage());

  await test.step("autorizar o microfone na página da extensão (primeiro uso)", async () => {
    const aba = await navegador.contexto.newPage();
    await aba.goto(navegador.url("microfone.html"));
    await expect(aba.locator("#status")).toContainText("Microfone liberado");
    await aba.close();
  });

  await test.step("abrir o atendimento do paciente no e-SUS PEC", async () => {
    await abrirPecFalso(pec, fixture.paciente);
    await expect(pec.getByRole("heading", { name: fixture.paciente.nome })).toBeVisible();
  });

  const tela = await navegador.abrirPopup(pec);
  popup = tela;

  await test.step("entrar como médica", async () => {
    await tela.getByLabel("E-mail").fill(fixture.medico.email);
    await tela.getByLabel("Senha").fill(fixture.medico.senha);
    await tela.getByLabel("Perfil").selectOption("medico");
    await tela.getByRole("button", { name: "Entrar" }).click();
    await expect(tela.getByRole("heading", { name: "Pacientes" })).toBeVisible();
  });

  await test.step("criar o paciente do atendimento", async () => {
    await tela.locator(".patient-controls button").click();
    await tela.getByPlaceholder("Nome do Paciente").fill(fixture.paciente.nome);
    await tela.getByRole("button", { name: "Criar" }).click();
    // O nome, não o pseudônimo "PAC-...": é ele que a conferência compara com o PEP.
    await expect(tela.getByRole("heading", { name: `Paciente: ${fixture.paciente.nome}` })).toBeVisible();
  });

  await test.step("gravar a consulta com o áudio de fixture", async () => {
    await tela.getByRole("button", { name: /Iniciar gravação/ }).click();
    // Uns segundos de áudio bastam: a transcrição de fixture só confere que chegou som.
    await expect(tela.getByText(/Gravando\.\.\. \(0:0[5-9]\)/)).toBeVisible({ timeout: 20_000 });
    await tela.getByRole("button", { name: /Parar/ }).click();
    // Envio das partes e transcrição: termina com "Arquivo salvo" ou com um aviso de erro (❌).
    const salvo = tela.getByText("✓ Arquivo salvo");
    await expect(salvo.or(tela.getByText(/^❌/))).toBeVisible({ timeout: 60_000 });
    await expect(salvo).toBeVisible();
    // A transcrição segue para o chat, e a IA (de fixture) responde.
    await expect(tela.locator(".chat-message-user").last()).toContainText(fixture.transcricao[1].texto);
    await expect(tela.locator(".chat-message-bot").last()).toContainText("Resposta fixa da IA");
    await test.info().attach("popup-depois-da-gravacao", { body: await tela.screenshot(), contentType: "image/png" });
  });

  const { consultationId, patientName } = await tela.evaluate(() =>
    chrome.storage.local.get(["consultationId", "patientName"]),
  );
  const rotaSoap = `/api/consultations/${consultationId}/soap`;
  let soap: SoapDocument | undefined;

  await test.step("gerar o SOAP da consulta (IA de fixture) e aprovar", async () => {
    const gerado = await chamarApi(tela, "POST", rotaSoap);
    expect(gerado.status).toBe(201);
    expect(gerado.dados.soap.status).toBe("gerado");
    expect(gerado.dados.soap.atual.subjetivo).toBe(fixture.soap.subjetivo);

    const aprovado = await chamarApi(tela, "POST", `${rotaSoap}/${gerado.dados.soap.id}/approve`);
    expect(aprovado.status).toBe(200);
    expect(aprovado.dados.soap.status).toBe("aprovado");
    soap = aprovado.dados.soap;
  });

  await test.step("inserir o SOAP aprovado no prontuário do e-SUS PEC", async () => {
    const aprovado = soap as SoapDocument;
    const status = await comandoAoPep<RespostaStatusPep>(tela, { type: "pep:status" });
    expect(status?.pep).toBe("esus-pec");
    // O paciente do cabeçalho do PEC é o mesmo da consulta: o botão não pede confirmação.
    expect(conferirPaciente(status?.paciente ?? null, { nome: patientName })).toEqual({ situacao: "igual" });

    const escrita = await comandoAoPep<RespostaEscritaPep>(tela, {
      type: "pep:write",
      text: formatSoapForPep(aprovado.atual, "esus-pec"),
    });
    expect(escrita?.resultado).toEqual({ ok: true });

    const registro = await chamarApi(tela, "POST", `${rotaSoap}/${aprovado.id}/inserted`, { pep: "esus-pec" });
    expect(registro.status).toBe(200);
    expect(registro.dados.soap.status).toBe("inserido_no_pep");
  });

  await test.step("conferir o SOAP nos campos do e-SUS PEC", async () => {
    expect(await textoDaSecao(pec, "textFieldSubjetivo")).toBe(fixture.soap.subjetivo);
    expect(await textoDaSecao(pec, "observacoesObjetivo")).toBe(fixture.soap.objetivo);
    const avaliacao = await textoDaSecao(pec, "TextFieldObservacaoAvaliacao");
    expect(avaliacao).toContain(fixture.soap.avaliacao);
    expect(avaliacao).toContain(`(CID-10 ${fixture.soap.hipoteses[0].cid10})`);
    const plano = await textoDaSecao(pec, "textFieldPlano");
    expect(plano).toContain(fixture.soap.plano);
    expect(plano).toContain(`- ${fixture.soap.pendencias[0]}`);
    await test.info().attach("pec-com-o-soap", { body: await pec.screenshot({ fullPage: true }), contentType: "image/png" });
  });
});
