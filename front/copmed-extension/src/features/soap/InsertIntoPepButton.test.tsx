// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import InsertIntoPepButton from "./InsertIntoPepButton";
import type { PonteDoPep } from "./pepDaAba";
import type { SoapDocument, SoapVersion } from "../shared/types";
import type { WriteEvolutionResult } from "../../pep/pepAdapter";
import { formatSoapForPep } from "../../pep/formatarSoap";
import { separarSecoesSoap } from "../../pep/esusPec";
import { markSoapInserted } from "../../services/api";

// B53 (US019-CA006): só habilitado após aprovar; nunca automático; o clique
// insere e o status vira inserido_no_pep.

vi.mock("../../services/api", () => ({ markSoapInserted: vi.fn() }));
const marcar = vi.mocked(markSoapInserted);

const VERSAO: SoapVersion = {
  subjetivo: "Tosse seca há três dias.",
  objetivo: "Ausculta sem ruídos.",
  avaliacao: "Infecção de vias aéreas superiores.",
  plano: "Hidratação e retorno se febre.",
  hipoteses: [{ descricao: "IVAS", cid10: "J06.9", confianca: "media" }],
  alertas: ["Febre persistente"],
  pendencias: ["Saturação"],
};

const soap = (status: SoapDocument["status"]): SoapDocument => ({
  id: "s1",
  consultation_id: "c1",
  status,
  schema_version: "SoapV1",
  prompt: null,
  versao_ia: VERSAO,
  versao_medico: null,
  atual: VERSAO,
  created_at: null,
  updated_at: null,
  approved_at: null,
  diff: null,
});

function ponte(pep: string | null, resultado: WriteEvolutionResult = { ok: true }) {
  return {
    pepDaAba: vi.fn(async () => pep),
    escrever: vi.fn(async () => (pep ? { pep, resultado } : null)),
  } satisfies PonteDoPep;
}

const botao = () => screen.getByRole("button") as HTMLButtonElement;

beforeEach(() => {
  marcar.mockReset();
  marcar.mockResolvedValue({ soap: soap("inserido_no_pep") });
});
afterEach(cleanup);

describe("Inserir no prontuário", () => {
  it("fica desabilitado até o SOAP ser aprovado, mesmo com PEP aberto", async () => {
    const p = ponte("esus-pec");
    for (const status of ["gerado", "editado"] as const) {
      const { unmount } = render(<InsertIntoPepButton consultationId="c1" soap={soap(status)} ponte={p} />);
      await waitFor(() => expect(p.pepDaAba).toHaveBeenCalled());
      expect(botao().disabled).toBe(true);
      expect(screen.getByText("Aprove o SOAP para inserir no prontuário.")).toBeTruthy();
      unmount();
    }
    expect(p.escrever).not.toHaveBeenCalled();
  });

  it("sem PEP na aba fica desabilitado e explica o motivo", async () => {
    render(<InsertIntoPepButton consultationId="c1" soap={soap("aprovado")} ponte={ponte(null)} />);
    await screen.findByText(/Abra o atendimento do paciente/);
    expect(botao().disabled).toBe(true);
  });

  it("nunca escreve sozinho: só no clique", async () => {
    const p = ponte("esus-pec");
    render(<InsertIntoPepButton consultationId="c1" soap={soap("aprovado")} ponte={p} />);
    await waitFor(() => expect(botao().disabled).toBe(false));
    expect(p.escrever).not.toHaveBeenCalled();
    expect(marcar).not.toHaveBeenCalled();
  });

  it("o clique escreve no PEP e registra inserido_no_pep", async () => {
    const p = ponte("esus-pec");
    const onInserted = vi.fn();
    render(<InsertIntoPepButton consultationId="c1" soap={soap("aprovado")} ponte={p} onInserted={onInserted} />);
    await waitFor(() => expect(botao().disabled).toBe(false));

    fireEvent.click(botao());

    await screen.findByText("SOAP inserido no e-SUS PEC.");
    expect(p.escrever).toHaveBeenCalledWith(formatSoapForPep(VERSAO, "esus-pec"));
    expect(marcar).toHaveBeenCalledWith("c1", "s1", "esus-pec");
    expect(onInserted).toHaveBeenCalledWith(expect.objectContaining({ status: "inserido_no_pep" }));
  });

  it("falha na escrita não registra nada e explica", async () => {
    const p = ponte("amplimed", { ok: false, motivo: "campo_nao_encontrado" });
    render(<InsertIntoPepButton consultationId="c1" soap={soap("aprovado")} ponte={p} />);
    await waitFor(() => expect(botao().disabled).toBe(false));

    fireEvent.click(botao());

    await screen.findByText(/Não encontrei o campo de evolução/);
    expect(marcar).not.toHaveBeenCalled();
  });

  it("texto inserido mas status não registrado: oferece só registrar, sem escrever de novo", async () => {
    marcar.mockRejectedValueOnce(new Error("Sem conexão"));
    const p = ponte("esus-pec");
    render(<InsertIntoPepButton consultationId="c1" soap={soap("aprovado")} ponte={p} />);
    await waitFor(() => expect(botao().disabled).toBe(false));

    fireEvent.click(botao());
    await screen.findByText(/Não insira de novo/);
    fireEvent.click(screen.getByRole("button", { name: "Registrar inserção" }));

    await screen.findByText("SOAP inserido no e-SUS PEC.");
    expect(p.escrever).toHaveBeenCalledTimes(1);
    expect(marcar).toHaveBeenCalledTimes(2);
  });

  it("SOAP já inserido não oferece inserir de novo", async () => {
    render(<InsertIntoPepButton consultationId="c1" soap={soap("inserido_no_pep")} ponte={ponte("esus-pec")} />);
    expect(botao().textContent).toBe("Inserido no prontuário");
    expect(botao().disabled).toBe(true);
  });
});

describe("formatSoapForPep", () => {
  it("gera as quatro seções que o e-SUS PEC distribui nos campos", () => {
    const secoes = separarSecoesSoap(formatSoapForPep(VERSAO));
    expect(secoes.subjetivo).toBe("Tosse seca há três dias.");
    expect(secoes.objetivo).toBe("Ausculta sem ruídos.");
    expect(secoes.avaliacao).toContain("IVAS (CID-10 J06.9) — confiança média");
    expect(secoes.avaliacao).toContain("Alertas:\n- Febre persistente");
    expect(secoes.plano).toContain("Pendências:\n- Saturação");
  });
});
