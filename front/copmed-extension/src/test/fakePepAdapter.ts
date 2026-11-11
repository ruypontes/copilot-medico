/**
 * Adaptador de PEP falso, para uso exclusivo em testes (B48).
 *
 * Este arquivo NÃO é código de produção. Ele existe para validar a
 * suíte de contrato (pepAdapterContract.ts) e o registry, sem depender
 * de um PEP real (Amplimed, e-SUS PEC) ou de DOM de verdade.
 *
 * A página fake é montada em memória, com HTML mínimo, dados 100%
 * fictícios e nenhum dado de paciente real (LGPD).
 */

import type {
  PepAdapter,
  PatientInfo,
  WriteEvolutionResult,
} from "../pep/pepAdapter";

/**
 * HTML da página fake do PEP. Tem os mesmos tipos de campo que o
 * Amplimed real (nome, idade, sexo, notas clínicas, campo de evolução),
 * mas com dados inventados. Os seletores usados pelo fake imitam a
 * estrutura de um prontuário, para o teste ficar realista.
 */
const HTML_PAGINA_FAKE = `
<!DOCTYPE html>
<html lang="pt-BR">
  <body>
    <header id="cabecalho-paciente">
      <h1 data-campo="nome-paciente">Paciente Fictício de Teste</h1>
      <span data-campo="idade-paciente">42 anos</span>
      <span data-campo="sexo-paciente">Feminino</span>
    </header>

    <section id="notas-clinicas">
      <div data-nota="anamnese">Paciente relata dor de cabeça há três dias.</div>
      <div data-nota="exame_fisico">PA 120/80, afebril, bom estado geral.</div>
      <div data-nota="conclusao_diagnostica">Cefaleia tensional.</div>
      <div data-nota="lista_problemas">Cefaleia tensional; estresse ocupacional.</div>
    </section>

    <section id="evolucao">
      <textarea data-campo="evolucao" rows="5"></textarea>
    </section>
  </body>
</html>
`;

/**
 * Cria uma nova página fake (um `Document` do jsdom) com o HTML acima.
 * É uma FÁBRICA, não uma constante: cada teste que precisar de página
 * limpa chama esta função e recebe um DOM novo. Isso evita que a
 * escrita de um teste interfira na leitura do próximo.
 */
export function criarPaginaPepFake(): Document {
  const parser = new DOMParser();
  return parser.parseFromString(HTML_PAGINA_FAKE, "text/html");
}

/**
 * Lê o conteúdo atual do campo de evolução da página fake. Usado nos
 * testes de contrato para confirmar que `writeEvolution` escreveu de
 * fato o texto no campo (e não só devolveu `{ ok: true }`).
 */
export function lerCampoEvolucaoFake(page: Document): string | null {
  const campo = page.querySelector<HTMLTextAreaElement>(
    "textarea[data-campo='evolucao']",
  );
  return campo ? campo.value : null;
}

/**
 * Extrai o texto de um elemento `data-campo` dentro do `Document`.
 * Devolve `null` se o elemento não existir, e devolve `null` também se
 * o texto estiver vazio depois de tirar espaços nas pontas. O contrato
 * de `readPatient` e `readClinicalNotes` proíbe valores vazios.
 */
function lerTextoDeCampo(page: Document, seletor: string): string | null {
  const elemento = page.querySelector(seletor);
  if (!elemento) return null;
  const texto = (elemento.textContent ?? "").trim();
  return texto.length > 0 ? texto : null;
}

/**
 * Adaptador fake. Cumpre o contrato de `PepAdapter` e usa a página
 * construída por `criarPaginaPepFake()` por padrão. Nunca lança erro
 * nos métodos de leitura/escrita — segue o contrato à risca.
 */
export function criarFakePepAdapter(): PepAdapter {
  return {
    id: "pep-fake",

    detect(page: Document = document): boolean {
      // A página é considerada o PEP fake quando tem o cabeçalho
      // identificado pelo id `cabecalho-paciente`. Não lança nunca.
      try {
        return page.querySelector("#cabecalho-paciente") !== null;
      } catch {
        return false;
      }
    },

    readPatient(page: Document = document): PatientInfo | null {
      try {
        const nome = lerTextoDeCampo(
          page,
          "[data-campo='nome-paciente']",
        );
        if (!nome) return null;

        const info: PatientInfo = { nome };
        const idade = lerTextoDeCampo(page, "[data-campo='idade-paciente']");
        const sexo = lerTextoDeCampo(page, "[data-campo='sexo-paciente']");
        if (idade) info.idade = idade;
        if (sexo) info.sexo = sexo;
        return info;
      } catch {
        return null;
      }
    },

    readClinicalNotes(page: Document = document): Record<string, string> | null {
      try {
        const notas: Record<string, string> = {};
        const elementos = page.querySelectorAll<HTMLElement>("[data-nota]");
        elementos.forEach((elemento) => {
          const chave = elemento.getAttribute("data-nota");
          const valor = (elemento.textContent ?? "").trim();
          if (chave && valor.length > 0) {
            notas[chave] = valor;
          }
        });
        return Object.keys(notas).length > 0 ? notas : null;
      } catch {
        return null;
      }
    },

    async writeEvolution(
      text: string,
      page: Document = document,
    ): Promise<WriteEvolutionResult> {
      // Regra 1: texto vazio (ou só espaços) nunca vai para o PEP.
      if (typeof text !== "string" || text.trim().length === 0) {
        return { ok: false, motivo: "texto_vazio" };
      }

      try {
        const campo = page.querySelector<HTMLTextAreaElement>(
          "textarea[data-campo='evolucao']",
        );
        if (!campo) {
          return { ok: false, motivo: "campo_nao_encontrado" };
        }
        campo.value = text;
        return { ok: true };
      } catch {
        // Regra de privacidade: a mensagem de erro nunca inclui o texto
        // do paciente. Aqui não há mensagem — só um motivo fixo.
        return { ok: false, motivo: "falha_ao_escrever" };
      }
    },
  };
}
