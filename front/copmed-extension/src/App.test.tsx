// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { API_URL, API_URL_KEY } from "./services/api";
import { RECORDING_STATE_KEY, type RecordingSnapshot } from "./features/recording/recordingProtocol";
import {
  P1,
  P2,
  PACIENTE_SALVO,
  TOKEN,
  chamadasPara,
  comandosDeGravacao,
  fake,
  gravacaoSalva,
  instalarFakes,
} from "./test/extensaoFake";
import fixtureAmplimed from "../tests/fixtures/pep/amplimed-consulta.html?raw";

// Testes de comportamento da extensão pela interface: a API e o chrome.storage são simulados,
// então os mesmos testes valem para qualquer organização interna do App.

beforeEach(instalarFakes);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function abrirComPacienteSalvo() {
  Object.assign(fake.session, TOKEN);
  Object.assign(fake.store, PACIENTE_SALVO);
  const view = render(<App />);
  await screen.findByText("Paciente: Fulano Teste");
  await screen.findByText("Resposta da consulta A");
  await waitFor(() => expect(screen.getByPlaceholderText("Digite sua mensagem...")).toBeTruthy());
  return view;
}

describe("sessão", () => {
  it("sem token salvo mostra o login e não chama a API", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Entrar" });
    expect(fake.chamadas).toEqual([]);
  });

  it("token inválido é apagado e volta ao login com aviso", async () => {
    Object.assign(fake.session, TOKEN);
    fake.authMeStatus = 401;
    render(<App />);
    await screen.findByText("Sessão expirada. Entre novamente.");
    expect(fake.chamadas[0]).toMatchObject({ method: "GET", path: "/api/auth/me", auth: "Bearer tok-salvo" });
    expect(fake.session.copmed_extension_token).toBeUndefined();
    expect(fake.store.copmed_extension_token).toBeUndefined();
  });

  it("login guarda o token e abre o app sem paciente", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Entrar" });
    fireEvent.change(screen.getByPlaceholderText("medico@clinica.com"), { target: { value: "medico@teste.com" } });
    fireEvent.change(screen.getByPlaceholderText("Sua senha"), { target: { value: "senha123" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await screen.findByRole("button", { name: "Sair" });
    expect(chamadasPara("POST", "/api/auth/login")[0].body).toEqual({
      email: "medico@teste.com",
      password: "senha123",
      profile: "medico",
    });
    // B27: o token fica em chrome.storage.session e nunca em disco (storage.local)
    expect(fake.session.copmed_extension_token).toBe("tok-novo");
    expect(fake.store.copmed_extension_token).toBeUndefined();
    await screen.findByText("Bem-vindo! Selecione ou crie um paciente para começar.");
    await waitFor(() => expect(chamadasPara("GET", "/api/all-patients")[0]?.auth).toBe("Bearer tok-novo"));
  });

  it("login sem senha mostra erro e não chama a API", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Entrar" });
    fireEvent.change(screen.getByPlaceholderText("medico@clinica.com"), { target: { value: "medico@teste.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
    await screen.findByText("Informe e-mail, senha e perfil.");
    expect(fake.chamadas).toEqual([]);
  });

  it("sair apaga sessão e paciente e volta ao login", async () => {
    await abrirComPacienteSalvo();
    fireEvent.click(screen.getByRole("button", { name: "Sair" }));
    await screen.findByRole("heading", { name: "Entrar" });
    expect(fake.session).toEqual({});
    // sobra so o API_URL que o popup publica para o background.js (nao e dado de usuario)
    expect(fake.store).toEqual({ [API_URL_KEY]: API_URL });
  });

  it("token antigo em storage.local é migrado para a sessão sem pedir novo login", async () => {
    Object.assign(fake.store, TOKEN); // como deixado por versoes anteriores da extensao
    render(<App />);
    await screen.findByText("Bem-vindo! Selecione ou crie um paciente para começar.");
    expect(fake.session.copmed_extension_token).toBe("tok-salvo");
    expect(fake.store.copmed_extension_token).toBeUndefined();
    expect(fake.chamadas[0]).toMatchObject({ path: "/api/auth/me", auth: "Bearer tok-salvo" });
    // espera a lista de pacientes terminar: uma chamada em voo vazaria para o teste seguinte
    await waitFor(() => expect(chamadasPara("GET", "/api/all-patients")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText("Carregando...")).toBeNull());
  });

  it("401 em uma chamada do app (depois de validar a sessão) volta ao login com aviso", async () => {
    Object.assign(fake.session, TOKEN);
    fake.pacientesStatus = 401; // /api/auth/me valida, mas a API recusa a proxima chamada (token revogado)
    render(<App />);

    await screen.findByText("Sessão expirada. Entre novamente.");
    await screen.findByRole("heading", { name: "Entrar" });
    expect(fake.session).toEqual({});
    expect(chamadasPara("GET", "/api/auth/me")).toHaveLength(1);
    expect(chamadasPara("GET", "/api/all-patients")).toHaveLength(1);
  });
});

describe("pacientes e consultas", () => {
  it("restaura o paciente salvo com consultas, histórico e transcrições", async () => {
    const { container } = await abrirComPacienteSalvo();
    const [seletorPaciente, seletorConsulta] = container.querySelectorAll<HTMLSelectElement>("select.patient-select");

    expect(seletorPaciente.value).toBe(P1.id);
    expect(Array.from(seletorPaciente.options).map((o) => o.textContent)).toEqual([
      "Selecione um Paciente",
      "Fulano Teste (p1aaaaaa...)",
      "Ciclano Teste (p2bbbbbb...)",
    ]);
    await waitFor(() =>
      expect(Array.from(seletorConsulta.options).map((o) => o.textContent)).toEqual([
        "Selecione uma Consulta",
        "Consulta B (c2yyyyyy...)",
        "Consulta A (c1xxxxxx...)",
      ])
    );
    expect(seletorConsulta.value).toBe("c1xxxxxxxx");
    screen.getByText("Pergunta da consulta A");
    await screen.findByRole("button", { name: "📂 Transcrições (1)" });
  });

  it("trocar de paciente abre a consulta mais recente dele", async () => {
    const { container } = await abrirComPacienteSalvo();
    const seletorPaciente = container.querySelector<HTMLSelectElement>("select.patient-select")!;
    fireEvent.change(seletorPaciente, { target: { value: P2.id } });

    await screen.findByText("Paciente: Ciclano Teste");
    await screen.findByText("Pergunta do retorno");
    expect(fake.store).toMatchObject({ patientId: P2.id, patientName: P2.name, consultationId: "c3zzzzzzzz" });
  });

  it("trocar de consulta carrega o histórico dela", async () => {
    const { container } = await abrirComPacienteSalvo();
    const seletorConsulta = container.querySelectorAll<HTMLSelectElement>("select.patient-select")[1];
    await waitFor(() => expect(seletorConsulta.disabled).toBe(false));
    fireEvent.change(seletorConsulta, { target: { value: "c2yyyyyyyy" } });

    await waitFor(() =>
      expect(chamadasPara("GET", `/api/patients/${P1.id}/consultations/c2yyyyyyyy/history`)).not.toHaveLength(0)
    );
    expect(fake.store).toMatchObject({ consultationId: "c2yyyyyyyy", consultationTitle: "Consulta B" });
    await waitFor(() => expect(screen.queryByText("Pergunta da consulta A")).toBeNull());
  });

  it("limpar o paciente volta para a mensagem inicial", async () => {
    const { container } = await abrirComPacienteSalvo();
    fireEvent.change(container.querySelector("select.patient-select")!, { target: { value: "" } });
    await screen.findByText("Bem-vindo! Selecione ou crie um paciente para começar.");
    expect(screen.queryByText(/^Paciente: /)).toBeNull();
  });

  it("cria paciente pelo modal e seleciona a primeira consulta", async () => {
    Object.assign(fake.session, TOKEN);
    const { container } = render(<App />);
    await screen.findByText("Bem-vindo! Selecione ou crie um paciente para começar.");
    fireEvent.click(container.querySelector(".patient-controls button")!);

    await screen.findByText("Criar Novo Paciente");
    fireEvent.change(screen.getByPlaceholderText("Nome do Paciente"), { target: { value: "Beltrano Novo" } });
    fireEvent.click(screen.getByRole("button", { name: "Criar" }));

    await screen.findByText("Paciente: Beltrano Novo");
    expect(chamadasPara("POST", "/api/patients")[0].body).toEqual({ name: "Beltrano Novo" });
    expect(fake.store).toMatchObject({ patientId: "p3ccccccccc", consultationId: "c5vvvvvvvv" });
    expect(screen.queryByText("Criar Novo Paciente")).toBeNull();
  });

  it("nova consulta é criada sem importar histórico", async () => {
    await abrirComPacienteSalvo();
    fireEvent.click(screen.getByRole("button", { name: "Nova Consulta" }));

    await waitFor(() => expect(fake.store.consultationId).toBe("c9novaaaaa"));
    const [criacao] = chamadasPara("POST", `/api/patients/${P1.id}/consultations`);
    expect(criacao.body).toMatchObject({ import_consultation_ids: [] });
    expect(String((criacao.body as { title: string }).title)).toMatch(/^Consulta em /);
    await waitFor(() => expect(screen.queryByText("Pergunta da consulta A")).toBeNull());
  });

  it("importar consulta cria uma nova com o histórico escolhido", async () => {
    await abrirComPacienteSalvo();
    fireEvent.click(screen.getByRole("button", { name: "Importar Consulta" }));

    const opcao = await screen.findByLabelText(/Consulta B/);
    expect(screen.queryByLabelText(/Consulta A/)).toBeNull();
    fireEvent.click(opcao);
    fireEvent.click(screen.getByRole("button", { name: "Criar Nova Consulta com Histórico(s)" }));

    await waitFor(() => expect(fake.store.consultationId).toBe("c9novaaaaa"));
    expect(chamadasPara("POST", `/api/patients/${P1.id}/consultations`)[0].body).toMatchObject({
      import_consultation_ids: ["c2yyyyyyyy"],
    });
  });
});

describe("chat e transcrições", () => {
  it("enviar mensagem chama /api/chat e recarrega o histórico", async () => {
    await abrirComPacienteSalvo();
    const campo = screen.getByPlaceholderText("Digite sua mensagem...");
    fireEvent.change(campo, { target: { value: "Como está a pressão?" } });
    fireEvent.submit(campo.closest("form")!);

    await screen.findByText("Resposta do assistente");
    expect(chamadasPara("POST", "/api/chat")[0].body).toEqual({
      message: "Como está a pressão?",
      patient_id: P1.id,
      consultation_id: "c1xxxxxxxx",
    });
  });

  it("abre e fecha uma transcrição salva", async () => {
    await abrirComPacienteSalvo();
    fireEvent.click(await screen.findByRole("button", { name: "📂 Transcrições (1)" }));
    fireEvent.click(await screen.findByText("0:42"));

    await screen.findByText("Bom dia, o que houve?");
    screen.getByText("Estou com dor de cabeça.");
    screen.getByText(/^Transcrição de /);
    fireEvent.click(screen.getByRole("button", { name: "Fechar arquivo" }));
    await waitFor(() => expect(screen.queryByText("Bom dia, o que houve?")).toBeNull());
  });

  it("extrai a fixture Amplimed e envia campos tipados para a rota pep-import", async () => {
    const fixtureHolder = document.createElement("div");
    fixtureHolder.innerHTML = fixtureAmplimed;
    document.body.append(fixtureHolder);

    try {
      await abrirComPacienteSalvo();
      fireEvent.click(screen.getByRole("button", { name: "Extrair Dados da Página" }));

      await waitFor(() => {
        expect(chamadasPara("POST", "/api/consultations/c1xxxxxxxx/pep-import")).toHaveLength(1);
      });
      expect(chamadasPara("POST", "/api/consultations/c1xxxxxxxx/pep-import")[0].body).toMatchObject({
        pep_origem: "amplimed",
        campos: {
          peso: "72.5",
          altura: "1.68",
          imc: "25.7",
          tempe: "37.8",
          freqres: "18",
          freqcar: "88",
          pas: "120",
          pad: "80",
          anamnese: "Paciente relata febre há 3 dias com tosse seca e dor de garganta.",
          exame_fisico: "Sem sinais de desidratação, murmúrio vesicular presente e sem roncos.",
          conclusao_diagnostica: "Quadro compatível com virose, manter hidratação e observação.",
          lista_problemas: "Febre, tosse, dor de garganta.",
        },
      });
    } finally {
      fixtureHolder.remove();
    }
  });
});

// B29: quem grava é o documento offscreen; o popup só envia comandos e mostra o estado que o
// background.js guarda em chrome.storage.session. "Reabrir o popup" = renderizar o App de novo
// com esse estado já salvo.
describe("gravação da consulta", () => {
  const EM_ANDAMENTO: Partial<RecordingSnapshot> = {
    status: "recording",
    recordingId: "gravacao-teste-0001",
    patientId: P1.id,
    consultationId: "c1xxxxxxxx",
  };
  const estadoSalvo = () => fake.session[RECORDING_STATE_KEY] as RecordingSnapshot;
  const botao = (name: string) => screen.getByRole<HTMLButtonElement>("button", { name });

  it("não grava sozinha; Iniciar envia o comando com paciente e consulta e liga o cronômetro", async () => {
    await abrirComPacienteSalvo();
    expect(comandosDeGravacao()).toEqual([]);
    expect(botao("⏹️ Parar").disabled).toBe(true);

    fireEvent.click(botao("🎙️ Iniciar gravação"));

    await screen.findByText(/● Gravando\.\.\. \(0:0\d\)/);
    expect(fake.mensagens.find((m) => m.type === "recording:start")).toMatchObject({
      target: "background",
      patientId: P1.id,
      consultationId: "c1xxxxxxxx",
    });
    botao("⏸️ Pausar");
    expect(botao("⏹️ Parar").disabled).toBe(false);
  });

  it("sem permissão do microfone abre a página de permissão em vez de gravar", async () => {
    fake.microfone = "prompt";
    await abrirComPacienteSalvo();

    fireEvent.click(botao("🎙️ Iniciar gravação"));

    await screen.findByText(/Autorize o microfone na aba que foi aberta/);
    expect(fake.abas).toEqual(["chrome-extension://copmed/microfone.html"]);
    expect(comandosDeGravacao()).toEqual([]);
  });

  it("reabrir o popup no meio da gravação restaura os controles e o cronômetro", async () => {
    gravacaoSalva({ ...EM_ANDAMENTO, accumulatedMs: 5 * 60_000, resumedAt: Date.now() - 65_000 });

    await abrirComPacienteSalvo();

    // 5 min já acumulados + 65 s do trecho em curso, contados enquanto o popup estava fechado
    await screen.findByText(/● Gravando\.\.\. \(6:0\d\)/);
    botao("⏸️ Pausar");
    expect(comandosDeGravacao()).toEqual([]); // reabrir não inicia nem interrompe nada
  });

  it("reabrir o popup com a gravação pausada mostra o tempo parado e permite retomar", async () => {
    gravacaoSalva({ ...EM_ANDAMENTO, status: "paused", accumulatedMs: 125_000, resumedAt: null });

    await abrirComPacienteSalvo();
    await screen.findByText("⏸️ Pausado (2:05)");

    fireEvent.click(botao("▶️ Retomar"));

    await screen.findByText(/● Gravando\.\.\. \(2:0\d\)/);
    expect(comandosDeGravacao()).toEqual(["recording:resume"]);
  });

  it("pausar congela o cronômetro e parar passa para o processamento", async () => {
    gravacaoSalva({ ...EM_ANDAMENTO, accumulatedMs: 0, resumedAt: Date.now() - 30_000 });
    await abrirComPacienteSalvo();
    await screen.findByText(/● Gravando/);

    fireEvent.click(botao("⏸️ Pausar"));
    await screen.findByText(/⏸️ Pausado \(0:3\d\)/);
    expect(estadoSalvo()).toMatchObject({ status: "paused", resumedAt: null });

    fireEvent.click(botao("⏹️ Parar"));
    await screen.findByText(/⏳ Processando\.\.\./);
    expect(comandosDeGravacao()).toEqual(["recording:pause", "recording:stop"]);
    // durante o processamento não dá para iniciar outra gravação
    expect(botao("🎙️ Iniciar gravação").disabled).toBe(true);
  });

  it("partes aguardando reenvio aparecem como aviso e a gravação continua", async () => {
    gravacaoSalva({
      ...EM_ANDAMENTO,
      resumedAt: Date.now(),
      chunksSent: 1,
      chunksPending: 2,
      warning: "upload_failed",
    });

    await abrirComPacienteSalvo();

    await screen.findByText("⚠️ 2 parte(s) do áudio aguardando reenvio. A gravação continua.");
    screen.getByText(/● Gravando/);
  });

  it("transcrição concluída com o popup fechado vai para o chat e o histórico ao reabrir", async () => {
    const logEntry = { id: 99, timestamp: "2026-01-02T10:00:00Z", duration: "120:00", consultation_id: "c1xxxxxxxx" };
    fake.transcricoesNovas = [logEntry]; // o backend já salvou a transcrição quando o popup reabre
    gravacaoSalva({
      result: {
        recordingId: "gravacao-teste-0001",
        patientId: P1.id,
        consultationId: "c1xxxxxxxx",
        stopReason: "limit",
        transcription: "Paciente relata febre há três dias.",
        logEntry,
        error: null,
        missingChunks: [2],
      },
    });

    await abrirComPacienteSalvo();

    await waitFor(() =>
      expect(chamadasPara("POST", "/api/chat")[0]?.body).toMatchObject({
        message: "Paciente relata febre há três dias.",
        consultation_id: "c1xxxxxxxx",
      })
    );
    // a transcrição nova aparece uma vez só, venha do resultado ou da lista do servidor
    await screen.findByRole("button", { name: "📂 Transcrições (2)" });
    screen.getByText(/atingiu o limite de 120 minutos/);
    screen.getByText(/Parte\(s\) 2 do áudio não foram enviadas ou transcritas/);
    // entregue uma única vez: o resultado sai do estado guardado
    expect(comandosDeGravacao()).toEqual(["recording:ack-result"]);
    await waitFor(() => expect(estadoSalvo().result).toBeNull());
    expect(chamadasPara("POST", "/api/chat")).toHaveLength(1);
  });

  it("gravação sem transcrição mostra o motivo e não envia nada ao chat", async () => {
    gravacaoSalva({
      result: {
        recordingId: "gravacao-teste-0002",
        patientId: P1.id,
        consultationId: "c1xxxxxxxx",
        stopReason: "manual",
        transcription: null,
        logEntry: null,
        error: "Não foi possível enviar o áudio ao servidor. Verifique a conexão e grave novamente.",
        missingChunks: [],
      },
    });

    await abrirComPacienteSalvo();

    await screen.findByText(/❌ Não foi possível enviar o áudio ao servidor/);
    expect(chamadasPara("POST", "/api/chat")).toEqual([]);
    expect(screen.queryByText("✓ Arquivo salvo")).toBeNull();
  });

  it("resultado de outra consulta espera até ela ser aberta", async () => {
    gravacaoSalva({
      result: {
        recordingId: "gravacao-teste-0003",
        patientId: P1.id,
        consultationId: "c2yyyyyyyy",
        stopReason: "manual",
        transcription: "Texto da consulta B",
        logEntry: null,
        error: null,
        missingChunks: [],
      },
    });

    const { container } = await abrirComPacienteSalvo(); // abre a consulta A
    await screen.findByRole("button", { name: "📂 Transcrições (1)" });
    expect(chamadasPara("POST", "/api/chat")).toEqual([]);
    expect(comandosDeGravacao()).toEqual([]);

    const seletorConsulta = container.querySelectorAll<HTMLSelectElement>("select.patient-select")[1];
    await waitFor(() => expect(seletorConsulta.disabled).toBe(false));
    fireEvent.change(seletorConsulta, { target: { value: "c2yyyyyyyy" } });

    await waitFor(() =>
      expect(chamadasPara("POST", "/api/chat")[0]?.body).toMatchObject({
        message: "Texto da consulta B",
        consultation_id: "c2yyyyyyyy",
      })
    );
  });

  it("gravação de outra consulta continua visível e pode ser parada", async () => {
    gravacaoSalva({ ...EM_ANDAMENTO, consultationId: "c2yyyyyyyy", resumedAt: Date.now() });

    await abrirComPacienteSalvo(); // consulta A aberta; a gravação é da consulta B

    await screen.findByText("⚠️ Esta gravação pertence a outra consulta.");
    fireEvent.click(botao("⏹️ Parar"));
    await screen.findByText(/⏳ Processando\.\.\./);
  });

  it("sair da conta cancela a gravação em andamento", async () => {
    gravacaoSalva({ ...EM_ANDAMENTO, resumedAt: Date.now() });
    await abrirComPacienteSalvo();
    await screen.findByText(/● Gravando/);

    fireEvent.click(botao("Sair"));

    await screen.findByRole("heading", { name: "Entrar" });
    expect(comandosDeGravacao()).toEqual(["recording:cancel"]);
    expect(fake.session).toEqual({});
  });
});

// A seleção de paciente/consulta fica em chrome.storage.local, que é do navegador e não da
// conta. Estes casos cobrem o que acontece quando ela não vale para quem entrou.
describe("seleção guardada que não vale mais", () => {
  const DE_OUTRA_CONTA = {
    patientId: "p9-de-outro-medico",
    patientName: "Paciente De Outro Médico",
    consultationId: "c9-de-outro-medico",
    consultationTitle: "Consulta alheia",
  };

  it("paciente de outra conta não é restaurado, não é consultado na API e sai do storage", async () => {
    Object.assign(fake.session, TOKEN);
    Object.assign(fake.store, DE_OUTRA_CONTA);

    render(<App />);

    await screen.findByText("Bem-vindo! Selecione ou crie um paciente para começar.");
    await waitFor(() => expect(fake.store.patientId).toBeUndefined());
    expect(fake.store.consultationId).toBeUndefined();
    expect(screen.queryByText(/Paciente De Outro Médico/)).toBeNull(); // o nome não vaza para a outra conta
    expect(fake.chamadas.filter((c) => c.path.includes("p9-de-outro-medico"))).toEqual([]);
    expect(screen.queryByRole("button", { name: "🎙️ Iniciar gravação" })).toBeNull();
  });

  it("falha ao carregar as consultas não vira opção selecionável", async () => {
    fake.consultasStatus = 403;
    Object.assign(fake.session, TOKEN);
    Object.assign(fake.store, PACIENTE_SALVO);

    const { container } = render(<App />);

    await screen.findByText("Paciente: Fulano Teste");
    await waitFor(() =>
      expect(chamadasPara("GET", `/api/patients/${P1.id}/consultations`)).not.toHaveLength(0)
    );
    const seletorConsulta = container.querySelectorAll<HTMLSelectElement>("select.patient-select")[1];
    await waitFor(() => expect(seletorConsulta.disabled).toBe(true));
    expect(Array.from(seletorConsulta.options).map((o) => o.textContent)).toEqual(["Selecione uma Consulta"]);
  });

  it("consulta guardada que não existe é desfeita e não dá para gravar nela", async () => {
    Object.assign(fake.session, TOKEN);
    Object.assign(fake.store, { ...PACIENTE_SALVO, consultationId: "1791857915655", consultationTitle: "Erro de rede" });

    const { container } = render(<App />);

    await screen.findByText("Paciente: Fulano Teste");
    await waitFor(() => expect(fake.store.consultationId).toBeUndefined());
    const seletorConsulta = container.querySelectorAll<HTMLSelectElement>("select.patient-select")[1];
    await waitFor(() => expect(seletorConsulta.value).toBe(""));
    expect(fake.store.patientId).toBe(P1.id); // o paciente continua selecionado
    await waitFor(() => expect(screen.queryByRole("button", { name: "🎙️ Iniciar gravação" })).toBeNull());
    expect(comandosDeGravacao()).toEqual([]);
  });

  it("parte recusada pelo servidor aparece como erro durante a gravação", async () => {
    gravacaoSalva({
      status: "recording",
      recordingId: "gravacao-teste-0001",
      patientId: P1.id,
      consultationId: "c1xxxxxxxx",
      resumedAt: Date.now(),
      chunksRejected: 1,
    });

    await abrirComPacienteSalvo();

    await screen.findByText(/O servidor recusou 1 parte\(s\) do áudio/);
  });
});
