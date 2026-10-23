// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SoapDocument, SoapV1 } from "../shared/types";

const api = vi.hoisted(() => ({
  approveConsultationSoap: vi.fn(),
  generateConsultationSoap: vi.fn(),
  getConsultationSoap: vi.fn(),
  searchCid10: vi.fn(),
  updateConsultationSoap: vi.fn(),
}));

vi.mock("../../services/api", () => api);

import SoapEditor from "./SoapEditor";

const soap: SoapV1 = {
  subjetivo: "Cefaleia há dois dias.",
  objetivo: "Sem sinais vitais.",
  avaliacao: "Cefaleia.",
  plano: "Investigar evolução.",
  hipoteses: [{ descricao: "Cefaleia", cid10: "R51", confianca: "media" }],
  alertas: ["Retornar se piora"],
  pendencias: ["Aferir pressão"],
};

const documento: SoapDocument = {
  id: "soap-1",
  consultation_id: "consulta-1",
  versao_ia: soap,
  versao_medico: null,
  status: "gerado",
  criado_em: "2026-10-18T10:00:00Z",
  aprovado_em: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getConsultationSoap.mockResolvedValue({ soap: null });
  api.generateConsultationSoap.mockResolvedValue({ soap: documento });
  api.updateConsultationSoap.mockImplementation(async (_id: string, _doc: string, draft: SoapV1) => ({
    soap: { ...documento, versao_medico: draft, status: "editado" },
  }));
  api.approveConsultationSoap.mockResolvedValue({
    soap: { ...documento, versao_medico: soap, status: "aprovado" },
  });
  api.searchCid10.mockResolvedValue({ results: [{ code: "R51", description: "Cefaleia" }] });
});

describe("SoapEditor", () => {
  it("gera, busca CID-10, salva a revisão e aprova o registro", async () => {
    render(<SoapEditor consultationId="consulta-1" />);
    fireEvent.click(screen.getByRole("button", { name: /Gerar SOAP/i }));

    expect((await screen.findByRole("textbox", { name: "Subjetivo" }) as HTMLTextAreaElement).value).toBe(soap.subjetivo);
    expect((screen.getByRole("textbox", { name: "Objetivo" }) as HTMLTextAreaElement).value).toBe(soap.objetivo);
    expect((screen.getByRole("textbox", { name: "Avaliação" }) as HTMLTextAreaElement).value).toBe(soap.avaliacao);
    expect((screen.getByRole("textbox", { name: "Plano" }) as HTMLTextAreaElement).value).toBe(soap.plano);

    fireEvent.change(screen.getByRole("textbox", { name: "Buscar CID-10 para hipótese 1" }), {
      target: { value: "cef" },
    });
    expect(await screen.findByRole("button", { name: /R51 Cefaleia/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /R51 Cefaleia/ }));

    fireEvent.change(screen.getByRole("textbox", { name: "Plano" }), {
      target: { value: "Solicitar retorno." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Aprovar/ }));

    await waitFor(() => expect(api.updateConsultationSoap).toHaveBeenCalledWith(
      "consulta-1",
      "soap-1",
      expect.objectContaining({ plano: "Solicitar retorno." })
    ));
    await waitFor(() => expect(api.approveConsultationSoap).toHaveBeenCalledWith("consulta-1", "soap-1"));
    expect((await screen.findByRole("button", { name: "Aprovado" }) as HTMLButtonElement).disabled).toBe(true);
  });
});