// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixtureAmplimed from "../../tests/fixtures/pep/amplimed-consulta.html?raw";
import { pepRegistry } from "../pep/registry";
import { criarPaginaPec, PACIENTE_PEC } from "../test/esusPecPagina";
import {
  criarBotaoFlutuante,
  ID_DO_BOTAO,
  TEXTO_CANCELAR,
  TEXTO_CONFIRMAR,
  TEXTO_DO_BOTAO,
  type SelecaoDaExtensao,
} from "./botaoFlutuante";

// B52 (US019-CA005 / D-02): botão flutuante só em página de PEP detectada.

type Controle = ReturnType<typeof criarBotaoFlutuante>;
let controle: Controle;

// O shadow root é fechado: só o controle chega nele.
const botao = () => controle.raiz()?.querySelector<HTMLButtonElement>(".copmed-botao") ?? null;
const alerta = () => controle.raiz()?.querySelector<HTMLElement>("[role='alertdialog']") ?? null;
const botaoDoAlerta = (texto: string) =>
  [...(alerta()?.querySelectorAll("button") ?? [])].find((b) => b.textContent === texto) as HTMLButtonElement;

// Longo o bastante para o vi.waitFor (que avança os timers falsos) ver o aviso.
const AVISO_MS = 60_000;
let enviar: ReturnType<typeof vi.fn>;
let selecao: SelecaoDaExtensao;
let parar: (() => void) | null;

function iniciar(page: Document = document) {
  controle = criarBotaoFlutuante({
    registry: pepRegistry,
    selecaoAtual: async () => selecao,
    enviar,
    page,
    atrasoMs: 10,
    tempoDoAvisoMs: AVISO_MS,
  });
  controle.iniciar();
  parar = controle.parar;
  return controle;
}

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = "";
  enviar = vi.fn(async () => ({ ok: true }));
  selecao = { consultationId: "c1", paciente: { nome: PACIENTE_PEC.nome } };
  parar = null;
});

afterEach(() => {
  parar?.();
  vi.useRealTimers();
});

describe("botão flutuante", () => {
  it("não aparece fora de PEP", () => {
    document.body.innerHTML = "<main><h1>Internet banking</h1><input name='senha'></main>";
    iniciar();
    expect(botao()).toBeNull();
  });

  it("aparece no Amplimed e envia as notas lidas pelo adaptador", async () => {
    document.body.innerHTML = fixtureAmplimed;
    const controle = iniciar();
    expect(controle.adaptadorAtual()?.id).toBe("amplimed");

    botao()!.click();
    await vi.waitFor(() => expect(enviar).toHaveBeenCalledTimes(1));

    const [adaptador, campos, selecaoEnviada] = enviar.mock.calls[0];
    expect(adaptador.id).toBe("amplimed");
    expect(campos).toMatchObject({ peso: "72.5", anamnese: expect.stringContaining("febre") });
    expect(selecaoEnviada).toEqual(selecao);
    // O Amplimed ainda não lê o paciente: envia, mas avisa que não conferiu.
    await vi.waitFor(() => expect(botao()!.textContent).toBe("Dados enviados, sem conferir o paciente"));

    vi.advanceTimersByTime(AVISO_MS);
    expect(botao()!.textContent).toBe(TEXTO_DO_BOTAO);
    expect(botao()!.disabled).toBe(false);
  });

  it("aparece no e-SUS PEC", () => {
    iniciar(criarPaginaPec());
    expect(controle.adaptadorAtual()?.id).toBe("esus-pec");
    expect(botao()).not.toBeNull();
  });

  it("acompanha a navegação da SPA: some ao sair do prontuário e volta ao entrar", async () => {
    document.body.innerHTML = "<div id='app'>Lista de atendimentos</div>";
    iniciar();
    expect(botao()).toBeNull();

    document.getElementById("app")!.innerHTML = fixtureAmplimed;
    await vi.advanceTimersByTimeAsync(10);
    expect(botao()).not.toBeNull();

    document.getElementById("app")!.innerHTML = "Lista de atendimentos";
    await vi.advanceTimersByTimeAsync(10);
    expect(botao()).toBeNull();
  });

  it("mostra o erro da API sem travar o botão", async () => {
    document.body.innerHTML = fixtureAmplimed;
    enviar.mockResolvedValueOnce({ ok: false, mensagem: "Selecione paciente e consulta na extensao" });
    iniciar();

    botao()!.click();
    await vi.waitFor(() => expect(botao()!.textContent).toBe("Selecione paciente e consulta na extensao"));
    expect(botao()!.disabled).toBe(true); // não aceita clique duplo durante o aviso
    vi.advanceTimersByTime(AVISO_MS);
    expect(botao()!.disabled).toBe(false);
  });

  it("falha no envio vira aviso, não exceção", async () => {
    document.body.innerHTML = fixtureAmplimed;
    enviar.mockRejectedValueOnce(new Error("Extension context invalidated"));
    iniciar();

    botao()!.click();
    await vi.waitFor(() => expect(botao()!.textContent).toBe("Não foi possível enviar"));
  });

  it("isola o estilo no shadow DOM e não duplica o botão", async () => {
    document.body.innerHTML = fixtureAmplimed;
    iniciar();
    controle.atualizar();
    controle.atualizar();
    expect(document.querySelectorAll(`#${ID_DO_BOTAO}`)).toHaveLength(1);
    expect(controle.raiz()!.querySelector("style")).not.toBeNull();
    // Fechado: os scripts do PEP não leem o aviso com o nome do paciente do Copilot.
    expect(document.getElementById(ID_DO_BOTAO)!.shadowRoot).toBeNull();
  });
});

describe("botão flutuante: conferência do paciente (e-SUS PEC)", () => {
  it("mesmo paciente (sem acento, outra caixa, espaços extras): envia sem perguntar", async () => {
    selecao = { consultationId: "c1", paciente: { nome: "  PACIENTE   ficticio copmed " } };
    iniciar(criarPaginaPec());

    botao()!.click();
    await vi.waitFor(() => expect(enviar).toHaveBeenCalledTimes(1));
    expect(enviar.mock.calls[0][0].id).toBe("esus-pec");
    expect(enviar.mock.calls[0][1]).toMatchObject({ objetivo: expect.stringContaining("120/80") });
    await vi.waitFor(() => expect(botao()!.textContent).toBe("Dados enviados ao Copilot"));
    expect(alerta()).toBeNull();
  });

  it("paciente diferente: não envia e mostra os dois nomes", async () => {
    selecao = { consultationId: "c1", paciente: { nome: "Maria das Dores" } };
    iniciar(criarPaginaPec());

    botao()!.click();
    await vi.waitFor(() => expect(alerta()).not.toBeNull());
    expect(alerta()!.textContent).toContain(
      "Você está no prontuário de Paciente Fictício Copmed (Feminino, 38 anos e 2 meses), " +
        "mas a consulta selecionada no Copilot é de Maria das Dores.",
    );
    expect(alerta()!.textContent).toContain("Nada foi enviado.");
    expect(botao()!.disabled).toBe(true);
    expect(enviar).not.toHaveBeenCalled();

    // Cancelar é o padrão: nada sai.
    botaoDoAlerta(TEXTO_CANCELAR).click();
    await vi.waitFor(() => expect(botao()!.textContent).toBe("Envio cancelado"));
    expect(alerta()).toBeNull();
    expect(enviar).not.toHaveBeenCalled();
  });

  it("paciente diferente: só envia com a confirmação explícita do médico", async () => {
    selecao = { consultationId: "c1", paciente: { nome: "Maria das Dores" } };
    iniciar(criarPaginaPec());

    botao()!.click();
    await vi.waitFor(() => expect(alerta()).not.toBeNull());
    botaoDoAlerta(TEXTO_CONFIRMAR).click();

    await vi.waitFor(() => expect(enviar).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(botao()!.textContent).toBe("Dados enviados ao Copilot"));
  });

  it("a confirmação não vale se o PEP trocou de paciente com o aviso aberto", async () => {
    selecao = { consultationId: "c1", paciente: { nome: "Maria das Dores" } };
    const page = criarPaginaPec();
    iniciar(page);

    botao()!.click();
    await vi.waitFor(() => expect(alerta()).not.toBeNull());
    page.querySelector("header h2")!.textContent = "Outro Cidadão Fictício";
    botaoDoAlerta(TEXTO_CONFIRMAR).click();

    await vi.waitFor(() => expect(botao()!.textContent).toBe("O prontuário mudou de paciente: nada foi enviado"));
    expect(enviar).not.toHaveBeenCalled();
  });

  it("PEP sem paciente no cabeçalho: envia como antes, mas avisa que não conferiu", async () => {
    iniciar(criarPaginaPec({ paciente: null }));

    botao()!.click();
    await vi.waitFor(() => expect(enviar).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(botao()!.textContent).toBe("Dados enviados, sem conferir o paciente"));
    expect(alerta()).toBeNull();
  });

  it("nome do paciente do Copilot indisponível (pseudônimo): envia e avisa", async () => {
    selecao = { consultationId: "c1", paciente: { nome: "PAC-0123456789AB" } };
    iniciar(criarPaginaPec());

    botao()!.click();
    await vi.waitFor(() => expect(botao()!.textContent).toBe("Dados enviados, sem conferir o paciente"));
    expect(enviar).toHaveBeenCalledTimes(1);
  });
});
