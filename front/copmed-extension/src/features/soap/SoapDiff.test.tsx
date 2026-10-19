// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import SoapDiff from "./SoapDiff";
import type { SoapDiffResult } from "../shared/types";

// B44: o diff IA x médico fica visível depois da edição. O formato é o que a API
// devolve em GET /api/consultations/<id>/soap (backend/soap/diff.py).

const DIFF: SoapDiffResult = {
  alterado: true,
  secoes_alteradas: ["plano", "pendencias"],
  secoes: [
    {
      secao: "subjetivo",
      titulo: "Subjetivo",
      tipo: "texto",
      alterada: false,
      trechos: [{ op: "igual", texto: "Febre há três dias." }],
    },
    {
      secao: "plano",
      titulo: "Plano",
      tipo: "texto",
      alterada: true,
      trechos: [
        { op: "igual", texto: "Hidratação oral e retorno em " },
        { op: "removido", texto: "48" },
        { op: "adicionado", texto: "24" },
        { op: "igual", texto: " horas." },
      ],
    },
    {
      secao: "pendencias",
      titulo: "Pendências",
      tipo: "lista",
      alterada: true,
      trechos: [
        { op: "igual", texto: "Hemograma" },
        { op: "adicionado", texto: "Sorologia para dengue" },
      ],
    },
  ],
};

afterEach(cleanup);

describe("SoapDiff", () => {
  it("mostra o que o médico removeu e incluiu em cada seção alterada", () => {
    const { container } = render(<SoapDiff diff={DIFF} />);

    expect(screen.getByText(/2 seções alteradas pelo médico/)).toBeTruthy();
    const plano = screen.getByRole("region", { name: "Plano" });
    expect(plano.querySelector(".soap-diff-texto del")?.textContent).toBe("48");
    expect(plano.querySelector(".soap-diff-texto ins")?.textContent).toBe("24");
    expect(plano.textContent).toContain("Hidratação oral e retorno em 4824 horas.");

    const pendencias = screen.getByRole("region", { name: "Pendências" });
    expect(pendencias.querySelector("li.soap-diff-item-adicionado ins")?.textContent).toBe(
      "Sorologia para dengue",
    );
    // seção sem alteração fica escondida por padrão
    expect(screen.queryByRole("region", { name: "Subjetivo" })).toBeNull();
    expect(container.querySelectorAll(".soap-diff-selo")).toHaveLength(2);
  });

  it("permite ver também as seções sem alteração", () => {
    render(<SoapDiff diff={DIFF} />);

    fireEvent.click(screen.getByRole("button", { name: "Mostrar todas as seções" }));
    expect(screen.getByRole("region", { name: "Subjetivo" }).textContent).toContain("Febre há três dias.");

    fireEvent.click(screen.getByRole("button", { name: "Mostrar só as alteradas" }));
    expect(screen.queryByRole("region", { name: "Subjetivo" })).toBeNull();
  });

  it("sem edição do médico avisa que o texto é o da IA", () => {
    render(<SoapDiff diff={null} />);
    expect(screen.getByText(/Sem edição do médico/)).toBeTruthy();
  });

  it("edição igual à IA não mostra diferenças", () => {
    render(<SoapDiff diff={{ ...DIFF, alterado: false, secoes_alteradas: [] }} />);
    expect(screen.getByText(/não alterou o texto gerado pela IA/)).toBeTruthy();
    expect(screen.queryByRole("region")).toBeNull();
  });
});
