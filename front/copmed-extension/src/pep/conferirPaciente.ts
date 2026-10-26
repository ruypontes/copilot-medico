/**
 * Conferência do paciente: o prontuário aberto na aba é do mesmo paciente
 * selecionado no Copilot?
 *
 * O botão flutuante manda as notas do PEP para a consulta selecionada no
 * popup, e o "Inserir no prontuário" escreve o SOAP dessa consulta no PEP da
 * aba. Nada liga um ao outro: com o paciente trocado, dados de uma pessoa iam
 * parar no registro de outra. Antes de enviar ou inserir, os dois fluxos
 * comparam o paciente lido do cabeçalho do PEP com o selecionado.
 *
 * A comparação é só local, no navegador: nenhum nome sai daqui.
 */

import type { PatientInfo } from "./pepAdapter";

export type ConferenciaPaciente =
  | { situacao: "igual" }
  | { situacao: "divergente"; noPep: string; selecionado: string }
  /** Sem como conferir: segue como antes, mas avisando o médico. */
  | { situacao: "nao_conferido"; motivo: "pep_sem_paciente" | "selecao_sem_nome" };

/** Pseudônimo que a API devolve quando o nome está cifrado e o cofre não abriu (B26). */
const PSEUDONIMO = /^PAC-[0-9A-F]{12}$/i;
/** Nome padrão da API para paciente sem nome (repositories/pacientes.py). */
const SEM_NOME = "desconhecido";

/** Sem acento, sem pontuação, minúsculo e com um espaço só entre as palavras. */
export function normalizarNome(nome: string): string {
  return nome
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function nomeUtil(info: PatientInfo | null): string | null {
  const nome = info?.nome?.trim();
  if (!nome || PSEUDONIMO.test(nome) || normalizarNome(nome) === SEM_NOME) return null;
  return nome;
}

/** "Masculino"/"Feminino" viram "m"/"f"; indeterminado ou ignorado não conta. */
function sexo(info: PatientInfo): string | null {
  const s = normalizarNome(info.sexo ?? "");
  return s.startsWith("masc") ? "m" : s.startsWith("fem") ? "f" : null;
}

/** Idade em anos ("38 anos e 2 meses" → 38); meses ou dias contam como 0. */
function anos(info: PatientInfo): number | null {
  const idade = normalizarNome(info.idade ?? "");
  if (!idade) return null;
  const emAnos = idade.match(/^(\d+) anos?\b/);
  if (emAnos) return Number(emAnos[1]);
  return /^\d+ (mes|meses|dias?)\b/.test(idade) ? 0 : null;
}

function descrever(info: PatientInfo, nome: string): string {
  const detalhes = [info.sexo?.trim(), info.idade?.trim()].filter(Boolean);
  return detalhes.length ? `${nome} (${detalhes.join(", ")})` : nome;
}

/**
 * Compara o paciente do PEP com o selecionado no Copilot. O nome precisa ser
 * igual depois de normalizado: na dúvida é "divergente", porque o custo de
 * um aviso a mais é um clique e o de um paciente trocado é o prontuário
 * errado. Sexo e idade só contam quando os dois lados os informam (a idade
 * tolera 1 ano: aniversário entre o cadastro e hoje).
 */
export function conferirPaciente(
  doPep: PatientInfo | null,
  selecionado: PatientInfo | null,
): ConferenciaPaciente {
  const nomePep = nomeUtil(doPep);
  if (!doPep || !nomePep) return { situacao: "nao_conferido", motivo: "pep_sem_paciente" };
  const nomeSelecionado = nomeUtil(selecionado);
  if (!selecionado || !nomeSelecionado) return { situacao: "nao_conferido", motivo: "selecao_sem_nome" };

  const sexoPep = sexo(doPep);
  const sexoSelecionado = sexo(selecionado);
  const anosPep = anos(doPep);
  const anosSelecionado = anos(selecionado);
  const mesmo =
    normalizarNome(nomePep) === normalizarNome(nomeSelecionado) &&
    (sexoPep === null || sexoSelecionado === null || sexoPep === sexoSelecionado) &&
    (anosPep === null || anosSelecionado === null || Math.abs(anosPep - anosSelecionado) <= 1);

  return mesmo
    ? { situacao: "igual" }
    : {
        situacao: "divergente",
        noPep: descrever(doPep, nomePep),
        selecionado: descrever(selecionado, nomeSelecionado),
      };
}

/** Mesmo paciente na tela? Usado para conferir de novo depois da confirmação. */
export function mesmoPacienteNaTela(antes: PatientInfo | null, agora: PatientInfo | null): boolean {
  const a = nomeUtil(antes);
  const b = nomeUtil(agora);
  return a !== null && b !== null && normalizarNome(a) === normalizarNome(b);
}

export function mensagemDivergencia(c: { noPep: string; selecionado: string }): string {
  return `Você está no prontuário de ${c.noPep}, mas a consulta selecionada no Copilot é de ${c.selecionado}.`;
}

export const MENSAGEM_NAO_CONFERIDO: Record<
  Extract<ConferenciaPaciente, { situacao: "nao_conferido" }>["motivo"],
  string
> = {
  pep_sem_paciente: "Não foi possível conferir o paciente: o prontuário não mostra o nome dele.",
  selecao_sem_nome: "Não foi possível conferir o paciente: o nome do paciente selecionado no Copilot não está disponível.",
};
