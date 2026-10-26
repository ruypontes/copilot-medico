// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixtureAmplimed from "../../tests/fixtures/pep/amplimed-consulta.html?raw";
import { pepRegistry } from "../pep/registry";
import { criarPaginaPec } from "../test/esusPecPagina";
import { criarBotaoFlutuante, ID_DO_BOTAO, TEXTO_DO_BOTAO } from "./botaoFlutuante";

// B52 (US019-CA005 / D-02): botão flutuante só em página de PEP detectada.

const botao = (page: Document = document) =>
  page.getElementById(ID_DO_BOTAO)?.shadowRoot?.querySelector("button") ?? null;

// Longo o bastante para o vi.waitFor (que avança os timers falsos) ver o aviso.
const AVISO_MS = 60_000;
let enviar: ReturnType<typeof vi.fn>;
let parar: (() => void) | null;

function iniciar(page: Document = document) {
  const controle = criarBotaoFlutuante({ registry: pepRegistry, enviar, page, atrasoMs: 10, tempoDoAvisoMs: AVISO_MS });
  controle.iniciar();
  parar = controle.parar;
  return controle;
}

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = "";
  enviar = vi.fn(async () => ({ ok: true }));
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

    const [adaptador, campos] = enviar.mock.calls[0];
    expect(adaptador.id).toBe("amplimed");
    expect(campos).toMatchObject({ peso: "72.5", anamnese: expect.stringContaining("febre") });
    await vi.waitFor(() => expect(botao()!.textContent).toBe("Dados enviados ao Copilot"));

    vi.advanceTimersByTime(AVISO_MS);
    expect(botao()!.textContent).toBe(TEXTO_DO_BOTAO);
    expect(botao()!.disabled).toBe(false);
  });

  it("aparece no e-SUS PEC", () => {
    const page = criarPaginaPec();
    const controle = iniciar(page);
    expect(controle.adaptadorAtual()?.id).toBe("esus-pec");
    expect(botao(page)).not.toBeNull();
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
    const controle = iniciar();
    controle.atualizar();
    controle.atualizar();
    expect(document.querySelectorAll(`#${ID_DO_BOTAO}`)).toHaveLength(1);
    expect(document.getElementById(ID_DO_BOTAO)!.shadowRoot!.querySelector("style")).not.toBeNull();
  });
});
