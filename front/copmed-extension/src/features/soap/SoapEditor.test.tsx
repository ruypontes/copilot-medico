// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { SoapDocument, SoapVersion } from "../shared/types";

// B43 (US018): gerar, editar (seções, hipóteses com CID-10, alertas e pendências)
// e aprovar. A API é falsa; o SoapV1 de verdade é testado no backend (B39).

const api = vi.hoisted(() => {
  class ApiError extends Error {
    status: number;
    errors: string[];
    constructor(message: string, status: number, errors: string[] = []) {
      super(message);
      this.status = status;
      this.errors = errors;
    }
  }
  return {
    ApiError,
    getSoap: vi.fn(),
    generateSoap: vi.fn(),
    saveSoapDoctorVersion: vi.fn(),
    approveSoap: vi.fn(),
    searchCid10: vi.fn(),
    markSoapInserted: vi.fn(),
  };
});
vi.mock("../../services/api", () => api);
// Sem aba de PEP no teste: o "Inserir no prontuário" aparece, desabilitado.
vi.mock("./pepDaAba", () => ({
  ponteChrome: { pepDaAba: async () => null, pacienteDaAba: async () => null, escrever: async () => null },
}));

import SoapEditor from "./SoapEditor";
import { normalizarCid10 } from "./cid10";

const IA: SoapVersion = {
  subjetivo: "Cefaleia há dois dias.",
  objetivo: "PA 120x80.",
  avaliacao: "Cefaleia tensional provável.",
  plano: "Analgésico e retorno.",
  hipoteses: [{ descricao: "Cefaleia tensional", cid10: "G44.2", confianca: "media" }],
  alertas: ["Piora súbita"],
  pendencias: [],
};

function documento(status: SoapDocument["status"], medico: SoapVersion | null = null): SoapDocument {
  return {
    id: "soap-1",
    consultation_id: "c1",
    status,
    schema_version: "SoapV1",
    prompt: { id: "soap", versao: "1" },
    versao_ia: IA,
    versao_medico: medico,
    atual: medico || IA,
    created_at: null,
    updated_at: null,
    approved_at: null,
    diff: medico
      ? {
          alterado: true,
          secoes_alteradas: ["plano"],
          secoes: [
            {
              secao: "plano",
              titulo: "Plano",
              tipo: "texto",
              alterada: true,
              trechos: [{ op: "adicionado", texto: "Retorno em 7 dias." }],
            },
          ],
        }
      : null,
  };
}

const campo = (nome: string) => screen.getByRole("textbox", { name: nome }) as HTMLTextAreaElement;
const botao = (nome: RegExp | string) => screen.getByRole("button", { name: nome }) as HTMLButtonElement;

beforeEach(() => {
  vi.clearAllMocks();
  api.getSoap.mockResolvedValue({ soap: null });
  api.generateSoap.mockResolvedValue({ soap: documento("gerado") });
  api.saveSoapDoctorVersion.mockImplementation(async (_c: string, _s: string, versao: SoapVersion) => ({
    soap: documento("editado", versao),
  }));
  api.approveSoap.mockImplementation(async () => {
    const gravadas = api.saveSoapDoctorVersion.mock.calls;
    const medico = gravadas.length ? (gravadas[gravadas.length - 1][2] as SoapVersion) : null;
    return { soap: { ...documento("editado", medico), status: "aprovado" } };
  });
  api.searchCid10.mockResolvedValue({ results: [{ code: "R51", description: "Cefaléia" }] });
});
afterEach(cleanup);

describe("SoapEditor", () => {
  it("sem consulta não mostra nada", () => {
    const { container } = render(<SoapEditor consultationId={null} patientName={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("gera, edita as seções, escolhe o CID-10, mexe nas listas e aprova", async () => {
    render(<SoapEditor consultationId="c1" patientName="Maria" />);
    fireEvent.click(await screen.findByRole("button", { name: /Gerar SOAP/ }));

    expect((await screen.findByRole("textbox", { name: "Subjetivo" }) as HTMLTextAreaElement).value).toBe(IA.subjetivo);
    for (const [nome, valor] of [["Objetivo", IA.objetivo], ["Avaliação", IA.avaliacao], ["Plano", IA.plano]]) {
      expect(campo(nome).value).toBe(valor);
    }
    expect(screen.getByText("Gerado pela IA")).toBeTruthy();
    expect(api.generateSoap).toHaveBeenCalledWith("c1");

    fireEvent.change(campo("Plano"), { target: { value: "Analgésico. Retorno em 7 dias." } });

    // Nova hipótese: o CID-10 vem da busca e a descrição, da tabela
    fireEvent.click(botao("Adicionar hipótese"));
    const cid = screen.getByRole("combobox", { name: "CID-10 da hipótese 2" });
    fireEvent.focus(cid);
    fireEvent.change(cid, { target: { value: "cefal" } });
    fireEvent.click(await screen.findByRole("button", { name: /R51 Cefaléia/ }));
    expect(api.searchCid10).toHaveBeenCalledWith("cefal");
    expect((screen.getByRole("textbox", { name: "Descrição da hipótese 2" }) as HTMLInputElement).value).toBe("Cefaléia");

    // Pendência nova e um item em branco que não vai para a API
    fireEvent.click(botao("Adicionar pendência"));
    fireEvent.change(screen.getByRole("textbox", { name: "Pendências: item 1" }), { target: { value: "Fundo de olho" } });
    fireEvent.click(botao("Adicionar alerta"));

    fireEvent.click(botao(/^Aprovar$/));

    await waitFor(() => expect(api.approveSoap).toHaveBeenCalledWith("c1", "soap-1"));
    // Editado: grava a versão do médico antes de aprovar
    expect(api.saveSoapDoctorVersion).toHaveBeenCalledWith("c1", "soap-1", {
      ...IA,
      plano: "Analgésico. Retorno em 7 dias.",
      hipoteses: [IA.hipoteses[0], { descricao: "Cefaléia", cid10: "R51", confianca: "baixa" }],
      alertas: ["Piora súbita"],
      pendencias: ["Fundo de olho"],
    });
    expect(api.saveSoapDoctorVersion.mock.invocationCallOrder[0]).toBeLessThan(
      api.approveSoap.mock.invocationCallOrder[0],
    );

    // Aprovado: só leitura e libera o "Inserir no prontuário" (B53)
    expect((await screen.findByRole("button", { name: "Aprovado" })).hasAttribute("disabled")).toBe(true);
    expect(campo("Plano").disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Salvar" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Adicionar hipótese" })).toBeNull();
    expect(screen.getByRole("button", { name: /Inserir no prontuário/ })).toBeTruthy();
  });

  it("sem edição aprova direto, sem gravar versão do médico", async () => {
    api.getSoap.mockResolvedValue({ soap: documento("gerado") });
    api.approveSoap.mockResolvedValue({ soap: documento("aprovado") });
    render(<SoapEditor consultationId="c1" patientName={null} />);

    await screen.findByRole("textbox", { name: "Plano" });
    expect(botao("Salvar").disabled).toBe(true);
    fireEvent.click(botao(/^Aprovar$/));
    await screen.findByRole("button", { name: "Aprovado" });
    expect(api.saveSoapDoctorVersion).not.toHaveBeenCalled();
  });

  it("mostra os erros do SoapV1 campo a campo e não aprova", async () => {
    api.getSoap.mockResolvedValue({ soap: documento("gerado") });
    api.saveSoapDoctorVersion.mockRejectedValue(
      new api.ApiError("SOAP invalido", 400, ["plano: nao pode ser vazio (ou e curto demais)"]),
    );
    render(<SoapEditor consultationId="c1" patientName={null} />);

    fireEvent.change(await screen.findByRole("textbox", { name: "Plano" }), { target: { value: " " } });
    fireEvent.click(botao(/^Aprovar$/));

    const alerta = await screen.findByRole("alert");
    expect(within(alerta).getByText("plano: nao pode ser vazio (ou e curto demais)")).toBeTruthy();
    expect(api.approveSoap).not.toHaveBeenCalled();
    // A edição continua na tela para o médico corrigir
    expect(campo("Plano").value).toBe(" ");
  });

  it("abre um SOAP editado com o diff IA x médico e permite descartar a edição local", async () => {
    const medico = { ...IA, plano: "Retorno em 7 dias." };
    api.getSoap.mockResolvedValue({ soap: documento("editado", medico) });
    render(<SoapEditor consultationId="c1" patientName={null} />);

    expect((await screen.findByRole("textbox", { name: "Plano" }) as HTMLTextAreaElement).value).toBe(medico.plano);
    expect(screen.getByText("Editado pelo médico")).toBeTruthy();
    fireEvent.click(botao(/Ver alterações/));
    expect(screen.getByText("Retorno em 7 dias.", { selector: "ins" })).toBeTruthy();

    fireEvent.change(campo("Plano"), { target: { value: "Outro plano" } });
    expect(botao(/Gerar de novo/).disabled).toBe(true);
    fireEvent.click(botao(/Descartar/));
    expect(campo("Plano").value).toBe(medico.plano);
  });

  it("SOAP já inserido no PEP abre só leitura", async () => {
    api.getSoap.mockResolvedValue({ soap: documento("inserido_no_pep") });
    render(<SoapEditor consultationId="c1" patientName={null} />);
    expect((await screen.findByRole("textbox", { name: "Subjetivo" }) as HTMLTextAreaElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: /Gerar/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Inserido no prontuário" })).toBeTruthy();
  });

  it("falha ao gerar mostra a mensagem da API", async () => {
    api.generateSoap.mockRejectedValue(new api.ApiError("Limite de uso da IA atingido.", 429));
    render(<SoapEditor consultationId="c1" patientName={null} />);
    fireEvent.click(await screen.findByRole("button", { name: /Gerar SOAP/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("Limite de uso da IA atingido.");
  });

  it("CID-10 digitado: código válido é normalizado, texto solto volta ao valor gravado", async () => {
    api.getSoap.mockResolvedValue({ soap: documento("gerado") });
    api.searchCid10.mockResolvedValue({ results: [] });
    render(<SoapEditor consultationId="c1" patientName={null} />);

    const cid = (await screen.findByRole("combobox", { name: "CID-10 da hipótese 1" })) as HTMLInputElement;
    fireEvent.focus(cid);
    fireEvent.change(cid, { target: { value: "g442" } });
    fireEvent.blur(cid);
    expect(cid.value).toBe("G44.2");

    fireEvent.focus(cid);
    fireEvent.change(cid, { target: { value: "dor de cabeça" } });
    expect(await screen.findByText("Nenhum código encontrado.")).toBeTruthy();
    fireEvent.blur(cid);
    expect(cid.value).toBe("G44.2");
  });
});

describe("normalizarCid10", () => {
  it("aceita o formato do SoapV1", () => {
    expect(normalizarCid10("j111")).toBe("J11.1");
    expect(normalizarCid10(" A90 ")).toBe("A90");
    expect(normalizarCid10("U07.1")).toBe("U07.1");
    expect(normalizarCid10("cefaleia")).toBeNull();
    expect(normalizarCid10("A9")).toBeNull();
  });
});
