import { vi } from "vitest";
import {
  IDLE_SNAPSHOT,
  RECORDING_STATE_KEY,
  elapsedMs,
  normalizeSnapshot,
  type RecordingReply,
  type RecordingSnapshot,
} from "../features/recording/recordingProtocol";

// API do backend e chrome.storage simulados para os testes de comportamento do App.

type Consulta = { id: string; title: string; date: string };
type Historico = { role: string; parts: { text: string }[]; timestamp: string };
type Chamada = { method: string; path: string; body: unknown; auth: string | undefined };
type Mensagem = { type: string; target?: string; patientId?: string; consultationId?: string };
type Ouvinte = (changes: Record<string, { newValue?: unknown }>, area: string) => void;

export const P1 = { id: "p1aaaaaaaaa", name: "Fulano Teste" };
export const P2 = { id: "p2bbbbbbbbb", name: "Ciclano Teste" };
export const TOKEN = { copmed_extension_token: "tok-salvo" };
export const PACIENTE_SALVO = {
  patientId: P1.id,
  patientName: P1.name,
  consultationId: "c1xxxxxxxx",
  consultationTitle: "Consulta A",
};

// Estado da API e do chrome.storage simulados; recriado a cada teste por instalarFakes().
export const fake = {
  store: {} as Record<string, unknown>, // chrome.storage.local
  session: {} as Record<string, unknown>, // chrome.storage.session (token e sessao)
  chamadas: [] as Chamada[],
  mensagens: [] as Mensagem[], // comandos enviados ao background.js (chrome.runtime.sendMessage)
  abas: [] as string[], // abas abertas com chrome.tabs.create
  microfone: "granted" as PermissionState,
  authMeStatus: 200,
  pacientesStatus: 200, // 401 simula a sessao vencendo no meio do uso
  consultasStatus: 200, // 403 simula um paciente que nao e da conta que entrou
  pacientes: [] as { id: string; name: string }[],
  consultas: {} as Record<string, Consulta[]>,
  historicos: {} as Record<string, Historico[]>,
  transcricoesNovas: [] as Record<string, unknown>[], // salvas pelo backend depois da última abertura (P1)
};

function msg(role: string, text: string): Historico {
  return { role, parts: [{ text }], timestamp: "2026-01-01T10:00:00Z" };
}

function resposta(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) };
}

function api(method: string, path: string, body: Record<string, unknown>) {
  let m: RegExpMatchArray | null;
  if (path === "/api/auth/login") {
    return resposta(200, { token: "tok-novo", user: { email: body.email }, profile: { role: "medico" } });
  }
  if (path === "/api/auth/me") {
    return fake.authMeStatus === 200
      ? resposta(200, { user: { email: "medico@teste.com" }, profile: { role: "medico" } })
      : resposta(401, { message: "Token inválido" });
  }
  if (path === "/api/all-patients") {
    return fake.pacientesStatus === 200
      ? resposta(200, { status: "success", patients: fake.pacientes })
      : resposta(fake.pacientesStatus, { message: "Token inválido" });
  }
  if (path === "/api/patients" && method === "POST") {
    const novo = { id: "p3ccccccccc", name: String(body.name) };
    fake.pacientes = [...fake.pacientes, novo];
    fake.consultas[novo.id] = [{ id: "c5vvvvvvvv", title: "Primeira Consulta", date: "2026-04-01" }];
    return resposta(200, {
      status: "success",
      patient_id: novo.id,
      patient_name: novo.name,
      first_consultation_id: "c5vvvvvvvv",
    });
  }
  if ((m = path.match(/^\/api\/patients\/([^/]+)\/consultations$/))) {
    const pid = decodeURIComponent(m[1]);
    if (method === "POST") {
      fake.consultas[pid] = [...(fake.consultas[pid] || []), { id: "c9novaaaaa", title: "Consulta nova", date: "2026-05-01" }];
      return resposta(200, { status: "success", consultation_id: "c9novaaaaa", consultation_title: "Consulta nova" });
    }
    if (fake.consultasStatus !== 200) {
      return resposta(fake.consultasStatus, { status: "error", message: "Acesso negado ao paciente." });
    }
    return resposta(200, { status: "success", consultations: [...(fake.consultas[pid] || [])] });
  }
  if ((m = path.match(/^\/api\/patients\/[^/]+\/consultations\/([^/]+)\/history$/))) {
    return resposta(200, { status: "success", history: fake.historicos[decodeURIComponent(m[1])] || [] });
  }
  if ((m = path.match(/^\/api\/patients\/([^/]+)\/transcription-log$/))) {
    const logs =
      decodeURIComponent(m[1]) === P1.id
        ? [
            ...fake.transcricoesNovas,
            {
              id: 1,
              timestamp: "2026-01-01T10:00:00Z",
              duration: "0:42",
              consultation_id: "c1xxxxxxxx",
              dialogue: [
                { role: "Médico", role_key: "doctor", text: "Bom dia, o que houve?" },
                { role: "Paciente", role_key: "patient", text: "Estou com dor de cabeça." },
              ],
            },
          ]
        : [];
    return resposta(200, { status: "success", logs });
  }
  // Editor SOAP (B43) abre com a consulta: ainda sem SOAP, e a busca CID-10 vazia.
  if (/^\/api\/consultations\/[^/]+\/soap$/.test(path) && method === "GET") {
    return resposta(404, { status: "error", message: "Nenhum SOAP gerado para esta consulta." });
  }
  if (path.startsWith("/api/cid10")) {
    return resposta(200, { status: "success", query: "", count: 0, results: [] });
  }
  if ((m = path.match(/^\/api\/consultations\/([^/]+)\/pep-import$/)) && method === "POST") {
    const cid = decodeURIComponent(m[1]);
    fake.historicos[cid] = [
      ...(fake.historicos[cid] || []),
      msg("user", "Dados do PEP importados."),
      msg("model", "Dados analisados."),
    ];
    return resposta(200, { status: "success", consultation_id: cid });
  }
  if (path === "/api/chat") {
    const cid = String(body.consultation_id);
    fake.historicos[cid] = [
      ...(fake.historicos[cid] || []),
      msg("user", String(body.message)),
      msg("model", "Resposta do assistente"),
    ];
    return resposta(200, { status: "success" });
  }
  return resposta(404, { message: `rota não simulada: ${method} ${path}` });
}

export function instalarFakes() {
  fake.store = {};
  fake.session = {};
  fake.chamadas = [];
  fake.mensagens = [];
  fake.abas = [];
  fake.microfone = "granted";
  fake.authMeStatus = 200;
  fake.pacientesStatus = 200;
  fake.consultasStatus = 200;
  fake.pacientes = [P1, P2];
  fake.consultas = {
    [P1.id]: [
      { id: "c1xxxxxxxx", title: "Consulta A", date: "2026-01-01" },
      { id: "c2yyyyyyyy", title: "Consulta B", date: "2026-02-01" },
    ],
    [P2.id]: [
      { id: "c4wwwwwwww", title: "Primeira", date: "2025-12-01" },
      { id: "c3zzzzzzzz", title: "Retorno", date: "2026-03-01" },
    ],
  };
  fake.transcricoesNovas = [];
  fake.historicos = {
    c1xxxxxxxx: [msg("user", "Pergunta da consulta A"), msg("model", "Resposta da consulta A")],
    c3zzzzzzzz: [msg("user", "Pergunta do retorno")],
  };

  // Cada area le o objeto de fake.* no momento da chamada (os testes semeiam com Object.assign).
  const ouvintes = new Set<Ouvinte>();
  const avisar = (nome: string, changes: Record<string, { newValue?: unknown }>) =>
    setTimeout(() => ouvintes.forEach((ouvinte) => ouvinte(changes, nome)), 0);
  const area = (nome: string, dados: () => Record<string, unknown>) => ({
    get: (keys: string | string[], cb: (r: Record<string, unknown>) => void) => {
      const out: Record<string, unknown> = {};
      for (const k of Array.isArray(keys) ? keys : [keys]) if (k in dados()) out[k] = dados()[k];
      setTimeout(() => cb(out), 0);
    },
    set: (values: Record<string, unknown>, cb?: () => void) => {
      Object.assign(dados(), values);
      avisar(nome, Object.fromEntries(Object.entries(values).map(([k, v]) => [k, { newValue: v }])));
      if (cb) setTimeout(cb, 0);
    },
    remove: (keys: string[], cb?: () => void) => {
      for (const k of keys) delete dados()[k];
      avisar(nome, Object.fromEntries(keys.map((k) => [k, {}])));
      if (cb) setTimeout(cb, 0);
    },
  });
  const sessao = area("session", () => fake.session);

  // No lugar do background.js + documento offscreen: aplica o comando ao estado da gravação
  // guardado em chrome.storage.session, como o background real faz.
  function background(mensagem: Mensagem): RecordingReply {
    const atual = normalizeSnapshot(fake.session[RECORDING_STATE_KEY]);
    const gravar = (snapshot: RecordingSnapshot) => {
      sessao.set({ [RECORDING_STATE_KEY]: snapshot });
      return { ok: true, snapshot };
    };
    switch (mensagem.type) {
      case "recording:sync":
        return { ok: true, snapshot: atual };
      case "recording:start":
        return gravar({
          ...IDLE_SNAPSHOT,
          status: "recording",
          recordingId: "gravacao-teste-0001",
          patientId: mensagem.patientId ?? null,
          consultationId: mensagem.consultationId ?? null,
          resumedAt: Date.now(),
        });
      case "recording:pause":
        return gravar({ ...atual, status: "paused", accumulatedMs: elapsedMs(atual, Date.now()), resumedAt: null });
      case "recording:resume":
        return gravar({ ...atual, status: "recording", resumedAt: Date.now() });
      case "recording:stop":
        return gravar({ ...atual, status: "finalizing", accumulatedMs: elapsedMs(atual, Date.now()), resumedAt: null });
      case "recording:ack-result":
        return gravar({ ...atual, result: null });
      case "recording:cancel":
        sessao.remove([RECORDING_STATE_KEY]);
        return { ok: true, snapshot: IDLE_SNAPSHOT };
      default:
        return { ok: false, error: "unknown_command" };
    }
  }

  const chromeFake = {
    storage: {
      local: area("local", () => fake.store),
      session: sessao,
      onChanged: {
        addListener: (ouvinte: Ouvinte) => ouvintes.add(ouvinte),
        removeListener: (ouvinte: Ouvinte) => ouvintes.delete(ouvinte),
      },
    },
    runtime: {
      lastError: undefined,
      getURL: (caminho: string) => `chrome-extension://copmed/${caminho}`,
      sendMessage: (mensagem: Mensagem, cb?: (reply: RecordingReply) => void) => {
        fake.mensagens.push(mensagem);
        const resposta = background(mensagem);
        if (cb) setTimeout(() => cb(resposta), 0);
      },
    },
    tabs: {
      create: ({ url }: { url: string }) => fake.abas.push(url),
      query: vi.fn(async () => [{ id: 1 }]),
    },
    scripting: {
      executeScript: vi.fn(async (injection: { func: () => unknown }) => [
        { result: injection.func() },
      ]),
    },
  };
  vi.stubGlobal("chrome", chromeFake);

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const path = new URL(url).pathname;
      const method = init.method || "GET";
      const body = typeof init.body === "string" ? JSON.parse(init.body) : {};
      const headers = (init.headers || {}) as Record<string, string>;
      fake.chamadas.push({ method, path, body, auth: headers.Authorization });
      return api(method, path, body);
    })
  );

  // O popup só consulta a permissão do microfone: quem grava é o documento offscreen.
  Object.defineProperty(navigator, "permissions", {
    configurable: true,
    value: { query: async () => ({ state: fake.microfone }) },
  });
  Element.prototype.scrollIntoView = vi.fn();
  vi.spyOn(window, "alert").mockImplementation(() => {});
  vi.spyOn(console, "log").mockImplementation(() => {});
}

export function chamadasPara(method: string, path: string) {
  return fake.chamadas.filter((c) => c.method === method && c.path === path);
}

/** Comandos de gravação enviados ao background.js (sem o "recording:sync" de abertura). */
export function comandosDeGravacao() {
  return fake.mensagens.filter((m) => m.type !== "recording:sync").map((m) => m.type);
}

/** Semeia o estado da gravação como o background.js o deixaria em chrome.storage.session. */
export function gravacaoSalva(snapshot: Partial<RecordingSnapshot>) {
  fake.session[RECORDING_STATE_KEY] = { ...IDLE_SNAPSHOT, ...snapshot };
}
