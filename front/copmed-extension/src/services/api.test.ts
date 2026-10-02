import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  API_URL,
  API_URL_KEY,
  SessionExpiredError,
  apiRequest,
  clearSession,
  getStoredSession,
  login,
  publishApiUrl,
  setSessionExpiredHandler,
  setSessionRefresher,
  storeSession,
  type ExtensionSession,
} from "./api";

const TOKEN_KEY = "copmed_extension_token";
const USER_KEY = "copmed_extension_user";
const PROFILE_KEY = "copmed_extension_profile";

type Area = Record<string, unknown>;

/** chrome.storage em memoria, com a mesma API de callbacks da extensao. */
function makeArea(data: Area) {
  return {
    get: (keys: string[], cb: (r: Area) => void) =>
      cb(Object.fromEntries(keys.filter((k) => k in data).map((k) => [k, data[k]]))),
    set: (values: Area, cb: () => void) => {
      Object.assign(data, values);
      cb();
    },
    remove: (keys: string[], cb: () => void) => {
      keys.forEach((k) => delete data[k]);
      cb();
    },
  };
}

let local: Area;
let session: Area;
let fetchMock: ReturnType<typeof vi.fn>;

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });
const sessionOf = (token: string): ExtensionSession => ({
  token,
  user: { name: "Dra. Teste" },
  profile: { name: "medico" },
});
const bearerOf = (callIndex: number) =>
  (fetchMock.mock.calls[callIndex][1].headers as Record<string, string>).Authorization;

beforeEach(() => {
  local = {};
  session = {};
  fetchMock = vi.fn();
  vi.stubGlobal("chrome", { storage: { local: makeArea(local), session: makeArea(session) } });
  vi.stubGlobal("fetch", fetchMock);
  setSessionRefresher(null);
  setSessionExpiredHandler(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("armazenamento da sessao (B27)", () => {
  it("guarda token, usuario e perfil em storage.session e nada em storage.local", async () => {
    await storeSession(sessionOf("tok-1"));

    expect(session[TOKEN_KEY]).toBe("tok-1");
    expect(session[USER_KEY]).toBe(JSON.stringify({ name: "Dra. Teste" }));
    expect(session[PROFILE_KEY]).toBe(JSON.stringify({ name: "medico" }));
    expect(local).toEqual({});
  });

  it("le a sessao guardada", async () => {
    await storeSession(sessionOf("tok-1"));
    expect(await getStoredSession()).toEqual(sessionOf("tok-1"));
  });

  it("sem sessao devolve token nulo", async () => {
    expect(await getStoredSession()).toEqual({ token: null, user: null, profile: null });
  });

  it("clearSession apaga a sessao e qualquer copia persistente", async () => {
    await storeSession(sessionOf("tok-1"));
    local[TOKEN_KEY] = "tok-antigo";

    await clearSession();

    expect(session).toEqual({});
    expect(local).toEqual({});
  });

  it("nao apaga preferencias que nao sao da sessao", async () => {
    local.patientId = "p-1";
    await storeSession(sessionOf("tok-1"));
    await clearSession();
    expect(local.patientId).toBe("p-1");
  });

  it("publishApiUrl grava o API_URL em storage.local para o background.js", async () => {
    await publishApiUrl();
    expect(local[API_URL_KEY]).toBe(API_URL);
  });
});

describe("migracao do token antigo (storage.local -> storage.session)", () => {
  it("move o token legado para a sessao e apaga a copia em disco", async () => {
    local[TOKEN_KEY] = "tok-legado";
    local[USER_KEY] = JSON.stringify({ name: "Antigo" });
    local[PROFILE_KEY] = JSON.stringify({ name: "medico" });

    const stored = await getStoredSession();

    expect(stored.token).toBe("tok-legado");
    expect(stored.user).toEqual({ name: "Antigo" });
    expect(session[TOKEN_KEY]).toBe("tok-legado");
    expect(local[TOKEN_KEY]).toBeUndefined();
    expect(local[USER_KEY]).toBeUndefined();
    expect(local[PROFILE_KEY]).toBeUndefined();
  });

  it("nao sobrescreve uma sessao mais nova, mas ainda apaga o token legado do disco", async () => {
    session[TOKEN_KEY] = "tok-novo";
    local[TOKEN_KEY] = "tok-legado";

    const stored = await getStoredSession();

    expect(stored.token).toBe("tok-novo");
    expect(local[TOKEN_KEY]).toBeUndefined();
  });

  it("preserva as demais chaves de storage.local", async () => {
    local[TOKEN_KEY] = "tok-legado";
    local.consultationId = "c-1";

    await getStoredSession();

    expect(local.consultationId).toBe("c-1");
  });
});

describe("apiRequest: envio do token", () => {
  it("envia o token da sessao como Bearer", async () => {
    await storeSession(sessionOf("tok-1"));
    fetchMock.mockResolvedValueOnce(json(200, { status: "success" }));

    const data = await apiRequest("/api/all-patients");

    expect(data).toEqual({ status: "success" });
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_URL}/api/all-patients`);
    expect(bearerOf(0)).toBe("Bearer tok-1");
  });

  it("nao envia Authorization quando auth e false", async () => {
    await storeSession(sessionOf("tok-1"));
    fetchMock.mockResolvedValueOnce(json(200, {}));

    await apiRequest("/api/qualquer", { auth: false });

    expect(bearerOf(0)).toBeUndefined();
  });
});

describe("apiRequest: 401 central (B27)", () => {
  it("sem renovador: limpa a sessao, avisa a UI e lanca SessionExpiredError", async () => {
    await storeSession(sessionOf("tok-vencido"));
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);
    fetchMock.mockResolvedValueOnce(json(401, { message: "Token expirado" }));

    await expect(apiRequest("/api/all-patients")).rejects.toBeInstanceOf(SessionExpiredError);

    expect(onExpired).toHaveBeenCalledTimes(1);
    expect(session).toEqual({});
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("com renovador: 401 dispara a renovacao, repete a requisicao com o token novo e guarda a sessao", async () => {
    await storeSession(sessionOf("tok-vencido"));
    const onExpired = vi.fn();
    const refresher = vi.fn().mockResolvedValue(sessionOf("tok-novo"));
    setSessionExpiredHandler(onExpired);
    setSessionRefresher(refresher);
    fetchMock
      .mockResolvedValueOnce(json(401, { message: "Token expirado" }))
      .mockResolvedValueOnce(json(200, { status: "success", patients: [] }));

    const data = await apiRequest("/api/all-patients");

    expect(data).toEqual({ status: "success", patients: [] });
    expect(refresher).toHaveBeenCalledTimes(1);
    expect(refresher.mock.calls[0][0].token).toBe("tok-vencido");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(bearerOf(0)).toBe("Bearer tok-vencido");
    expect(bearerOf(1)).toBe("Bearer tok-novo");
    expect(session[TOKEN_KEY]).toBe("tok-novo");
    expect(onExpired).not.toHaveBeenCalled();
  });

  it("renovador que nao consegue renovar (null): expira a sessao", async () => {
    await storeSession(sessionOf("tok-vencido"));
    setSessionRefresher(vi.fn().mockResolvedValue(null));
    fetchMock.mockResolvedValueOnce(json(401, {}));

    await expect(apiRequest("/api/all-patients")).rejects.toBeInstanceOf(SessionExpiredError);

    expect(session).toEqual({});
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renovador que lanca erro: expira a sessao", async () => {
    await storeSession(sessionOf("tok-vencido"));
    setSessionRefresher(vi.fn().mockRejectedValue(new Error("rede")));
    fetchMock.mockResolvedValueOnce(json(401, {}));

    await expect(apiRequest("/api/all-patients")).rejects.toBeInstanceOf(SessionExpiredError);
    expect(session).toEqual({});
  });

  it("se o token renovado tambem for rejeitado (401), expira e nao entra em loop", async () => {
    await storeSession(sessionOf("tok-vencido"));
    const refresher = vi.fn().mockResolvedValue(sessionOf("tok-novo"));
    setSessionRefresher(refresher);
    fetchMock.mockResolvedValue(json(401, {}));

    await expect(apiRequest("/api/all-patients")).rejects.toBeInstanceOf(SessionExpiredError);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(refresher).toHaveBeenCalledTimes(1);
    expect(session).toEqual({});
  });

  it("varias requisicoes com 401 ao mesmo tempo compartilham uma unica renovacao", async () => {
    await storeSession(sessionOf("tok-vencido"));
    let release: (s: ExtensionSession) => void = () => {};
    const refresher = vi.fn(
      () => new Promise<ExtensionSession | null>((resolve) => (release = resolve))
    );
    setSessionRefresher(refresher);
    fetchMock.mockImplementation((_url: string, init: RequestInit) => {
      const auth = (init.headers as Record<string, string>).Authorization;
      return Promise.resolve(auth === "Bearer tok-novo" ? json(200, { ok: true }) : json(401, {}));
    });

    const all = Promise.all([apiRequest("/a"), apiRequest("/b"), apiRequest("/c")]);
    await vi.waitFor(() => expect(refresher).toHaveBeenCalled());
    release(sessionOf("tok-novo"));

    expect(await all).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(refresher).toHaveBeenCalledTimes(1);
  });

  it("401 no login (auth: false) e senha errada: nao apaga a sessao nem avisa a UI", async () => {
    await storeSession(sessionOf("tok-1"));
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);
    fetchMock.mockResolvedValueOnce(json(401, { message: "Email ou senha invalidos" }));

    const attempt = login({ email: "a@b.c", password: "x", profile: "medico" });

    await expect(attempt).rejects.toThrow("Email ou senha invalidos");
    await expect(attempt).rejects.not.toBeInstanceOf(SessionExpiredError);
    expect(onExpired).not.toHaveBeenCalled();
    expect(session[TOKEN_KEY]).toBe("tok-1");
  });

  it("erros que nao sao 401 (403, 500) nao expiram a sessao", async () => {
    await storeSession(sessionOf("tok-1"));
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);
    fetchMock
      .mockResolvedValueOnce(json(403, { message: "Acesso negado" }))
      .mockResolvedValueOnce(json(500, { message: "Erro interno" }));

    await expect(apiRequest("/api/x")).rejects.toThrow("Acesso negado");
    await expect(apiRequest("/api/y")).rejects.toThrow("Erro interno");

    expect(onExpired).not.toHaveBeenCalled();
    expect(session[TOKEN_KEY]).toBe("tok-1");
  });

  it("so o 401 dispara renovacao: 403 e 500 nao chamam o renovador", async () => {
    await storeSession(sessionOf("tok-1"));
    const refresher = vi.fn().mockResolvedValue(sessionOf("tok-novo"));
    setSessionRefresher(refresher);
    fetchMock
      .mockResolvedValueOnce(json(403, { message: "Acesso negado" }))
      .mockResolvedValueOnce(json(500, { message: "Erro interno" }));

    await expect(apiRequest("/api/x")).rejects.toThrow("Acesso negado");
    await expect(apiRequest("/api/y")).rejects.toThrow("Erro interno");

    expect(refresher).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("repete o corpo da requisicao ao tentar de novo apos renovar", async () => {
    await storeSession(sessionOf("tok-vencido"));
    setSessionRefresher(vi.fn().mockResolvedValue(sessionOf("tok-novo")));
    fetchMock
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValueOnce(json(200, { status: "success" }));

    await apiRequest("/api/chat", { method: "POST", body: JSON.stringify({ msg: "oi" }) });

    expect(fetchMock.mock.calls[0][1].body).toBe('{"msg":"oi"}');
    expect(fetchMock.mock.calls[1][1].body).toBe('{"msg":"oi"}');
  });
});
