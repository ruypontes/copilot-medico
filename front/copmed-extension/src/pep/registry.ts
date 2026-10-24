/**
 * Registro central de adaptadores de PEP.
 *
 * O registry guarda a lista de adaptadores disponíveis, sabe qual deles
 * corresponde a uma página (via `detect`) e devolve o adaptador certo
 * para leitura/escrita. Cada `createPepRegistry()` produz uma instância
 * ISOLADA — sem estado compartilhado entre instâncias, para que os
 * testes não interfiram uns nos outros.
 */

import type { PepAdapter, PepRegistry } from "./pepAdapter";

/**
 * Padrão do id do adaptador: apenas minúsculas, números e hífen.
 * Exemplos válidos: "amplimed", "esus-pec", "pep-2024".
 */
const PADRAO_ID = /^[a-z0-9-]+$/;

/**
 * Valida o id do adaptador. Lança erro com mensagem clara em português
 * quando o id não é string, é vazio, ou contém caracteres inválidos.
 * A asserção ajuda o TypeScript a saber que depois desta chamada o
 * valor é uma string válida.
 */
function validarId(id: unknown): asserts id is string {
  if (typeof id !== "string" || id.length === 0) {
    throw new Error("O id do adaptador de PEP deve ser um texto não vazio.");
  }
  if (!PADRAO_ID.test(id)) {
    throw new Error(
      `Id de adaptador inválido: "${id}". Use apenas minúsculas, números e hífen (ex.: "amplimed", "esus-pec").`,
    );
  }
}

/**
 * Cria uma nova instância de registry, com sua própria lista interna
 * de adaptadores. Duas instâncias criadas por esta função não
 * compartilham estado.
 */
export function createPepRegistry(): PepRegistry {
  // Array interno. Nunca exposto diretamente para fora da factory —
  // o método `list` devolve sempre uma cópia.
  const adaptadores: PepAdapter[] = [];

  return {
    register(adapter: PepAdapter): void {
      if (adapter === null || adapter === undefined || typeof adapter !== "object") {
        throw new Error("Não é possível registrar um adaptador nulo ou inválido.");
      }
      validarId(adapter.id);

      const jaExiste = adaptadores.some((a) => a.id === adapter.id);
      if (jaExiste) {
        throw new Error(
          `Já existe um adaptador registrado com o id "${adapter.id}".`,
        );
      }

      adaptadores.push(adapter);
    },

    list(): PepAdapter[] {
      // Sempre uma cópia. Alterar o array devolvido não afeta o interno.
      return adaptadores.slice();
    },

    get(id: string): PepAdapter | undefined {
      return adaptadores.find((a) => a.id === id);
    },

    detect(page: Document = document): PepAdapter | null {
      // Avalia em ordem de cadastro. O primeiro cujo `detect` devolver
      // `true` é o escolhido (empate resolve pelo primeiro).
      for (const adaptador of adaptadores) {
        try {
          if (adaptador.detect(page)) {
            return adaptador;
          }
        } catch {
          // Falha de um adaptador não deve derrubar os demais. Seguimos
          // para o próximo sem logar nada — pode ser DOM de outro PEP,
          // e o contrato do `detect` proíbe lançar erro de propósito.
        }
      }
      return null;
    },
  };
}

/**
 * Instância padrão, exportada para uso da aplicação. Quem precisar de
 * um registry isolado (ex.: testes) deve chamar `createPepRegistry()`
 * em vez de reutilizar esta.
 */
export const pepRegistry: PepRegistry = createPepRegistry();
