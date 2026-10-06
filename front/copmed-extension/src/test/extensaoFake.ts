import { vi } from "vitest";

// API do backend e chrome.storage simulados para os testes de comportamento do App.

type Consulta = { id: string; title: string; date: string };
type Historico = { role: string; parts: { text: string }[]; timestamp: string };
type Chamada = { method: string; path: string; body: unknown; auth: string | undefined };

export const P1 = { id: "p1aaaaaaaaa", name: "Fulano Teste" };
export const P2 = { id: "p2bbbbbbbbb", name: "Ciclano Teste" };
export const TOKEN = { copmed_extension_token: "tok-salvo" };
// Paciente e consulta ficam no chrome.storage.local; o token, no chrome.storage.session.
export const PACIENTE_SALVO = {
  patientId: P1.id,
  patientName: P1.name,
  consultationId: "c1xxxxxxxx",
  consultationTitle: "Consulta A",
};

// Estado da API e do chrome.storage simulados; recriado a cada teste por instalarFakes().
export const fake = {
  store: {} as Record<string, unknown>,
  // chrome.storage.session
  sessao: {} as Record<string, unknown>,
  chamadas: [] as Chamada[],
  authMeStatus: 200,
  // Tokens que a API simulada recusa com 401 e resposta do /api/auth/refresh.
  tokensExpirados: [] as string[],
  refreshStatus: 404,
  pacientes: [] as { id: string; name: string }[],
  consultas: {} as Record<string, Consulta[]>,
  historicos: {} as Record<string, Historico[]>,
};

function msg(role: string, text: string): Historico {
  return { role, parts: [{ text }], timestamp: "2026-01-01T10:00:00Z" };
}

function resposta(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) };
}

function api(method: string, path: string, body: Record<string, unknown>, auth: string | undefined) {
  let m: RegExpMatchArray | null;
  if (path === "/api/auth/login") {
    return resposta(200, {
      token: "tok-novo",
      refresh_token: "ref-novo",
      expires_in: 900,
      user: { email: body.email },
      profile: { role: "medico" },
    });
  }
  if (path === "/api/auth/refresh") {
    return fake.refreshStatus === 200
      ? resposta(200, { token: "tok-renovado", expires_in: 900 })
      : resposta(fake.refreshStatus, { message: "Refresh inválido" });
  }
  if (auth && fake.tokensExpirados.includes(auth.replace("Bearer ", ""))) {
    return resposta(401, { message: "Token expirado" });
  }
  if (path === "/api/auth/me") {
    return fake.authMeStatus === 200
      ? resposta(200, { user: { email: "medico@teste.com" }, profile: { role: "medico" } })
      : resposta(401, { message: "Token inválido" });
  }
  if (path === "/api/all-patients") return resposta(200, { status: "success", patients: fake.pacientes });
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
    return resposta(200, { status: "success", consultations: [...(fake.consultas[pid] || [])] });
  }
  if ((m = path.match(/^\/api\/patients\/[^/]+\/consultations\/([^/]+)\/history$/))) {
    return resposta(200, { status: "success", history: fake.historicos[decodeURIComponent(m[1])] || [] });
  }
  if ((m = path.match(/^\/api\/patients\/([^/]+)\/transcription-log$/))) {
    const logs =
      decodeURIComponent(m[1]) === P1.id
        ? [
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
  fake.sessao = {};
  fake.chamadas = [];
  fake.authMeStatus = 200;
  fake.tokensExpirados = [];
  fake.refreshStatus = 404;
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
  fake.historicos = {
    c1xxxxxxxx: [msg("user", "Pergunta da consulta A"), msg("model", "Resposta da consulta A")],
    c3zzzzzzzz: [msg("user", "Pergunta do retorno")],
  };

  const area = (dados: () => Record<string, unknown>) => ({
    get: (keys: string | string[], cb: (r: Record<string, unknown>) => void) => {
      const out: Record<string, unknown> = {};
      for (const k of Array.isArray(keys) ? keys : [keys]) if (k in dados()) out[k] = dados()[k];
      setTimeout(() => cb(out), 0);
    },
    set: (values: Record<string, unknown>, cb?: () => void) => {
      Object.assign(dados(), values);
      if (cb) setTimeout(cb, 0);
    },
    remove: (keys: string[], cb?: () => void) => {
      for (const k of keys) delete dados()[k];
      if (cb) setTimeout(cb, 0);
    },
  });
  const chromeFake = {
    storage: { local: area(() => fake.store), session: area(() => fake.sessao) },
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
      return api(method, path, body, headers.Authorization);
    })
  );

  // A gravação começa sozinha ao abrir uma consulta; aqui o microfone nunca responde.
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: () => new Promise(() => {}) },
  });
  Element.prototype.scrollIntoView = vi.fn();
  vi.spyOn(window, "alert").mockImplementation(() => {});
  vi.spyOn(console, "log").mockImplementation(() => {});
}

export function chamadasPara(method: string, path: string) {
  return fake.chamadas.filter((c) => c.method === method && c.path === path);
}
