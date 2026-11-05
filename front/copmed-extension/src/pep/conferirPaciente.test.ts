import { describe, expect, it } from "vitest";
import { conferirPaciente, mesmoPacienteNaTela, normalizarNome } from "./conferirPaciente";

// Proteção contra paciente trocado entre o PEP da aba e a consulta do Copilot.

describe("conferirPaciente", () => {
  it("normaliza acento, caixa, pontuação e espaços", () => {
    expect(normalizarNome("  José  da   SILVA-Conceição ")).toBe("jose da silva conceicao");
  });

  it("mesmo nome depois de normalizado é igual", () => {
    expect(conferirPaciente({ nome: "João Antônio Souza" }, { nome: "joao antonio  SOUZA" })).toEqual({
      situacao: "igual",
    });
  });

  it("nome diferente diverge, com os detalhes que cada lado informou", () => {
    expect(
      conferirPaciente({ nome: "Ana Lima", sexo: "Feminino", idade: "38 anos e 2 meses" }, { nome: "Ana Lins" }),
    ).toEqual({ situacao: "divergente", noPep: "Ana Lima (Feminino, 38 anos e 2 meses)", selecionado: "Ana Lins" });
  });

  it("nome abreviado num dos lados ainda diverge (na dúvida, pergunta)", () => {
    expect(conferirPaciente({ nome: "Maria Aparecida da Silva" }, { nome: "Maria Silva" }).situacao).toBe(
      "divergente",
    );
  });

  it("sexo e idade só contam quando os dois lados informam", () => {
    const pep = { nome: "Ana Lima", sexo: "Feminino", idade: "38 anos e 2 meses" };
    expect(conferirPaciente(pep, { nome: "Ana Lima" }).situacao).toBe("igual");
    expect(conferirPaciente(pep, { nome: "Ana Lima", sexo: "feminino", idade: "39 anos" }).situacao).toBe("igual");
    expect(conferirPaciente(pep, { nome: "Ana Lima", sexo: "Masculino" }).situacao).toBe("divergente");
    expect(conferirPaciente(pep, { nome: "Ana Lima", idade: "8 anos" }).situacao).toBe("divergente");
    expect(conferirPaciente(pep, { nome: "Ana Lima", sexo: "Ignorado" }).situacao).toBe("igual");
  });

  it("sem paciente no PEP não confere", () => {
    expect(conferirPaciente(null, { nome: "Ana Lima" })).toEqual({
      situacao: "nao_conferido",
      motivo: "pep_sem_paciente",
    });
    expect(conferirPaciente({ idade: "3 anos" }, { nome: "Ana Lima" }).situacao).toBe("nao_conferido");
  });

  it("sem nome útil do lado do Copilot (pseudônimo, Desconhecido, vazio) não confere", () => {
    for (const nome of ["PAC-0123456789AB", "Desconhecido", "  "]) {
      expect(conferirPaciente({ nome: "Ana Lima" }, { nome })).toEqual({
        situacao: "nao_conferido",
        motivo: "selecao_sem_nome",
      });
    }
    expect(conferirPaciente({ nome: "Ana Lima" }, null).situacao).toBe("nao_conferido");
  });

  it("mesmoPacienteNaTela só é verdadeiro com o mesmo nome dos dois lados", () => {
    expect(mesmoPacienteNaTela({ nome: "Ana Lima" }, { nome: "ANA  LIMA" })).toBe(true);
    expect(mesmoPacienteNaTela({ nome: "Ana Lima" }, { nome: "Ana Lins" })).toBe(false);
    expect(mesmoPacienteNaTela({ nome: "Ana Lima" }, null)).toBe(false);
    expect(mesmoPacienteNaTela(null, null)).toBe(false);
  });
});
