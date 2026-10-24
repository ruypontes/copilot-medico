/**
 * Contrato comum dos adaptadores de PEP (Prontuário Eletrônico do Paciente).
 *
 * Cada PEP suportado (Amplimed, e-SUS PEC, ...) implementa esta interface
 * em seu próprio arquivo, conforme ADR-06. O registry (registry.ts) é o
 * ponto central de descoberta e uso.
 *
 * Este arquivo contém APENAS tipos — nenhuma implementação, nenhum
 * import, nenhum efeito colateral no import.
 */

/**
 * Dados básicos do paciente lidos do cabeçalho do prontuário.
 * Todos os campos são opcionais e sempre texto — o adaptador só preenche
 * o que conseguir ler com segurança. Nunca inventar valor.
 */
export interface PatientInfo {
  nome?: string;
  idade?: string;
  sexo?: string;
}

/**
 * Motivos possíveis de falha ao tentar escrever a evolução no PEP.
 * São valores fixos para que o chamador possa tratar cada caso sem
 * precisar fazer parsing de mensagem.
 */
export type MotivoFalhaEscrita =
  | "texto_vazio"
  | "campo_nao_encontrado"
  | "falha_ao_escrever";

/**
 * Resultado explícito da tentativa de escrita. O adaptador NUNCA lança
 * erro — sempre devolve um destes dois formatos. Também NUNCA inclui
 * o texto do paciente na mensagem de erro (LGPD).
 */
export type WriteEvolutionResult =
  | { ok: true }
  | { ok: false; motivo: MotivoFalhaEscrita };

/**
 * Contrato que todo adaptador de PEP deve cumprir.
 *
 * Observações de contrato:
 * - `id` é obrigatório, não vazio, apenas minúsculas, números e hífen.
 *   Exemplos válidos: "amplimed", "esus-pec".
 * - `detect` é SÍNCRONO e NUNCA lança erro: se a página não for
 *   reconhecida ou o DOM estiver estranho, devolve `false`.
 * - Os métodos de leitura devolvem `null` quando o dado não é encontrado,
 *   em vez de objeto vazio ou valores inventados.
 * - `writeEvolution` devolve Promise de resultado explícito (nunca throw).
 */
export interface PepAdapter {
  readonly id: string;

  detect(page?: Document): boolean;

  readPatient(page?: Document): PatientInfo | null;

  readClinicalNotes(page?: Document): Record<string, string> | null;

  writeEvolution(text: string, page?: Document): Promise<WriteEvolutionResult>;
}

/**
 * Registro central de adaptadores. Uma instância mantém a lista de
 * adaptadores disponíveis e sabe escolher qual usar para uma página.
 */
export interface PepRegistry {
  /** Registra um adaptador. Rejeita id duplicado e id inválido. */
  register(adapter: PepAdapter): void;

  /** Devolve uma CÓPIA da lista de adaptadores registrados. */
  list(): PepAdapter[];

  /** Busca adaptador pelo id, ou `undefined` se não houver. */
  get(id: string): PepAdapter | undefined;

  /**
   * Detecta qual adaptador corresponde à página. Se nenhum der `true`,
   * devolve `null`. Em empate, devolve o primeiro cadastrado. Se o
   * `detect` de um adaptador lançar erro, ele é tratado como `false`
   * e não impede a avaliação dos demais.
   */
  detect(page?: Document): PepAdapter | null;
}
