// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getConsultationHistory: vi.fn(),
  sendChatMessage: vi.fn(),
  sendPepImport: vi.fn(),
  uploadPdf: vi.fn(),
}));
vi.mock("../../services/api", () => api);

import { useConsultationChat } from "./useConsultationChat";

function renderChat() {
  return renderHook(() =>
    useConsultationChat({
      patientId: "p1",
      consultationId: "c1",
      setPatientId: vi.fn(),
      setConsultationId: vi.fn(),
    })
  );
}

describe("useConsultationChat — B72 (resposta da IA sem travar em 'digitando')", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("chrome", { storage: { local: { set: vi.fn() } } });
  });

  it("mostra a resposta da IA assim que chega, sem recarregar o histórico", async () => {
    api.sendChatMessage.mockResolvedValue({ status: "success", ai_response: "Considere dengue." });
    const { result } = renderChat();

    await act(async () => {
      await result.current.handleSendMessage("Febre há 2 dias");
    });

    const textos = result.current.messages.map((m) => m.text);
    expect(textos).toEqual(["Febre há 2 dias", "Considere dengue."]);
    expect(result.current.isLoading).toBe(false);
    expect(api.getConsultationHistory).not.toHaveBeenCalled();
  });

  it("no timeout, libera o indicador e explica que a resposta fica salva no histórico", async () => {
    api.sendChatMessage.mockRejectedValue(new DOMException("tempo esgotado", "TimeoutError"));
    const { result } = renderChat();

    await act(async () => {
      await result.current.handleSendMessage("Pergunta longa");
    });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.messages.at(-1)?.text).toMatch(/demorando mais que o normal/);
  });

  it("sem ai_response no corpo, cai no comportamento antigo (recarrega o histórico)", async () => {
    api.sendChatMessage.mockResolvedValue({ status: "success" });
    api.getConsultationHistory.mockResolvedValue({ status: "success", history: [] });
    const { result } = renderChat();

    await act(async () => {
      await result.current.handleSendMessage("Oi");
    });

    expect(api.getConsultationHistory).toHaveBeenCalledWith("p1", "c1");
    expect(result.current.isLoading).toBe(false);
  });
});
