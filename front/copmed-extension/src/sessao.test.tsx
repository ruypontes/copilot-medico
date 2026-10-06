// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { getAuthenticatedUser, getPatients } from "./services/api";
import { P1, PACIENTE_SALVO, TOKEN, chamadasPara, fake, instalarFakes } from "./test/extensaoFake";

// B27: token no chrome.storage.session, renovação automática e tratamento central de 401.

beforeEach(instalarFakes);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const SESSAO_RENOVAVEL = {
  ...TOKEN,
  copmed_extension_refresh_token: "ref-salvo",
  copmed_extension_expires_at: Date.now() + 15 * 60_000,
};

describe("sessão no chrome.storage.session", () => {
  it("login guarda token, refresh e validade só no storage.session", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Entrar" });
    fireEvent.change(screen.getByPlaceholderText("medico@clinica.com"), { target: { value: "medico@teste.com" } });
    fireEvent.change(screen.getByPlaceholderText("Sua senha"), { target: { value: "senha123" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await screen.findByRole("button", { name: "Sair" });
    expect(fake.sessao).toMatchObject({
      copmed_extension_token: "tok-novo",
      copmed_extension_refresh_token: "ref-novo",
    });
    expect(fake.sessao.copmed_extension_expires_at).toBeGreaterThan(Date.now());
    expect(Object.keys(fake.store).filter((k) => k.startsWith("copmed_extension"))).toEqual([]);
    await waitFor(() => expect(chamadasPara("GET", "/api/all-patients")).toHaveLength(1));
  });

  it("sessão antiga no storage.local passa para o storage.session", async () => {
    Object.assign(fake.store, TOKEN);
    render(<App />);
    await screen.findByRole("button", { name: "Sair" });
    expect(chamadasPara("GET", "/api/auth/me")[0].auth).toBe("Bearer tok-salvo");
    expect(fake.sessao.copmed_extension_token).toBe("tok-salvo");
    expect(fake.store.copmed_extension_token).toBeUndefined();
    await waitFor(() => expect(chamadasPara("GET", "/api/all-patients")).toHaveLength(1));
  });
});

describe("401 e renovação", () => {
  it("401 dispara o refresh e repete a chamada com o token novo", async () => {
    Object.assign(fake.sessao, SESSAO_RENOVAVEL);
    fake.tokensExpirados = ["tok-salvo"];
    fake.refreshStatus = 200;
    render(<App />);

    await screen.findByRole("button", { name: "Sair" });
    expect(chamadasPara("POST", "/api/auth/refresh")[0].body).toEqual({ refresh_token: "ref-salvo" });
    expect(chamadasPara("GET", "/api/auth/me").map((c) => c.auth)).toEqual([
      "Bearer tok-salvo",
      "Bearer tok-renovado",
    ]);
    expect(fake.sessao.copmed_extension_token).toBe("tok-renovado");
    expect(fake.sessao.copmed_extension_refresh_token).toBe("ref-salvo");
    await waitFor(() => expect(chamadasPara("GET", "/api/all-patients")[0]?.auth).toBe("Bearer tok-renovado"));
  });

  it("chamadas ao mesmo tempo com 401 fazem um refresh só", async () => {
    Object.assign(fake.sessao, SESSAO_RENOVAVEL);
    fake.tokensExpirados = ["tok-salvo"];
    fake.refreshStatus = 200;

    const respostas = await Promise.all([getPatients(), getPatients(), getAuthenticatedUser()]);

    expect(respostas).toHaveLength(3);
    expect(chamadasPara("POST", "/api/auth/refresh")).toHaveLength(1);
    expect(chamadasPara("GET", "/api/all-patients").map((c) => c.auth)).toEqual([
      "Bearer tok-salvo",
      "Bearer tok-salvo",
      "Bearer tok-renovado",
      "Bearer tok-renovado",
    ]);
  });

  it("token perto de vencer é renovado antes da chamada", async () => {
    Object.assign(fake.sessao, { ...SESSAO_RENOVAVEL, copmed_extension_expires_at: Date.now() + 10_000 });
    fake.refreshStatus = 200;
    render(<App />);

    await screen.findByRole("button", { name: "Sair" });
    expect(chamadasPara("POST", "/api/auth/refresh")).toHaveLength(1);
    expect(chamadasPara("GET", "/api/auth/me")[0].auth).toBe("Bearer tok-renovado");
    await waitFor(() => expect(chamadasPara("GET", "/api/all-patients")).toHaveLength(1));
  });

  it("sem refresh possível, 401 durante o uso apaga a sessão e volta ao login", async () => {
    Object.assign(fake.store, PACIENTE_SALVO);
    Object.assign(fake.sessao, SESSAO_RENOVAVEL);
    fake.refreshStatus = 401;
    render(<App />);
    await screen.findByText(`Paciente: ${P1.name}`);
    await screen.findByText("Resposta da consulta A");
    await waitFor(() => expect(screen.getByPlaceholderText("Digite sua mensagem...")).toBeTruthy());

    fake.tokensExpirados = ["tok-salvo"];
    const campo = screen.getByPlaceholderText("Digite sua mensagem...");
    fireEvent.change(campo, { target: { value: "Oi" } });
    fireEvent.submit(campo.closest("form")!);

    await screen.findByText("Sessão expirada. Entre novamente.");
    expect(screen.getByRole("heading", { name: "Entrar" })).toBeTruthy();
    expect(chamadasPara("POST", "/api/auth/refresh")).toHaveLength(1);
    expect(fake.sessao).toEqual({});
  });
});
