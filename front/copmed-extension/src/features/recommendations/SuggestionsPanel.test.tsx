// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import SuggestionsPanel from "./SuggestionsPanel";
import * as api from "../../services/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const botao = () => screen.getByRole("button", { name: /Sugestões/ });

describe("SuggestionsPanel (B38)", () => {
  it("pede as sugestões da consulta com a janela escolhida e mostra os itens", async () => {
    const chamada = vi.spyOn(api, "getRecommendations").mockResolvedValue({
      itens: [
        { tipo: "pergunta", texto: "Perguntar sobre febre" },
        { tipo: "exame", texto: "Auscultar pulmões" },
      ],
    });
    render(<SuggestionsPanel patientId="p1" consultationId="c1" />);

    fireEvent.change(screen.getByLabelText("Janela das sugestões em minutos"), { target: { value: "10" } });
    fireEvent.click(botao());

    expect(await screen.findByText("Perguntar sobre febre")).toBeTruthy();
    expect(screen.getByText("Auscultar pulmões")).toBeTruthy();
    expect(screen.getByText("🩺 Exame")).toBeTruthy();
    expect(screen.getByText(/Não é gravado no prontuário/)).toBeTruthy();
    expect(chamada).toHaveBeenCalledWith({ patient_id: "p1", consultation_id: "c1", janela_min: 10 });
  });

  it("usa 5 minutos por padrão", async () => {
    const chamada = vi.spyOn(api, "getRecommendations").mockResolvedValue({ itens: [] });
    render(<SuggestionsPanel patientId="p1" consultationId="c1" />);

    fireEvent.click(botao());

    await waitFor(() => expect(chamada).toHaveBeenCalledWith(expect.objectContaining({ janela_min: 5 })));
    expect(await screen.findByText("Nenhuma sugestão no momento.")).toBeTruthy();
  });

  it("mostra o aviso da API quando não há transcrição na janela", async () => {
    vi.spyOn(api, "getRecommendations").mockResolvedValue({
      itens: [],
      message: "Nenhuma transcrição nos últimos 5 min.",
    });
    render(<SuggestionsPanel patientId="p1" consultationId="c1" />);

    fireEvent.click(botao());

    expect(await screen.findByText("Nenhuma transcrição nos últimos 5 min.")).toBeTruthy();
    expect(screen.queryByText("Nenhuma sugestão no momento.")).toBeNull();
  });

  it("mostra o erro quando a API falha", async () => {
    vi.spyOn(api, "getRecommendations").mockRejectedValue(new Error("Não foi possível gerar sugestões agora."));
    render(<SuggestionsPanel patientId="p1" consultationId="c1" />);

    fireEvent.click(botao());

    expect((await screen.findByRole("alert")).textContent).toContain("Não foi possível gerar sugestões");
  });

  it("trocar de consulta limpa as sugestões e ignora resposta atrasada", async () => {
    let responder: (valor: unknown) => void = () => {};
    vi.spyOn(api, "getRecommendations").mockImplementation(
      () => new Promise((resolve) => (responder = resolve))
    );
    const view = render(<SuggestionsPanel patientId="p1" consultationId="c1" />);

    fireEvent.click(botao());
    view.rerender(<SuggestionsPanel patientId="p1" consultationId="c2" />);
    responder({ itens: [{ tipo: "alerta", texto: "Da consulta anterior" }] });

    await waitFor(() => expect(botao().textContent).toContain("Sugestões"));
    expect(screen.queryByText("Da consulta anterior")).toBeNull();
  });

  it("sem consulta selecionada o botão fica desabilitado", () => {
    render(<SuggestionsPanel patientId="p1" consultationId={null} />);

    expect((botao() as HTMLButtonElement).disabled).toBe(true);
  });

  it("Fechar some com a lista", async () => {
    vi.spyOn(api, "getRecommendations").mockResolvedValue({ itens: [{ tipo: "alerta", texto: "Sinal de alarme" }] });
    render(<SuggestionsPanel patientId="p1" consultationId="c1" />);

    fireEvent.click(botao());
    fireEvent.click(await screen.findByRole("button", { name: "Fechar" }));

    expect(screen.queryByText("Sinal de alarme")).toBeNull();
  });
});
