/**
 * Tela de atendimento do e-SUS PEC falsa, servida no endereço do PEC local
 * (http://localhost:8081, em src/pep/dominios.ts). Assim o Chromium injeta o
 * content script de verdade, como faria no PEC.
 *
 * O HTML é o mesmo dos testes do EsusPecAdapter (src/test/esusPecPagina.ts).
 * O script abaixo faz o papel do Draft.js na colagem, como o `simularDraft`
 * de lá, mas dentro da página: o adaptador cola o texto e confere se ficou.
 */

import type { Page } from "@playwright/test";
import { htmlPaginaPec, type PacientePec } from "../src/test/esusPecPagina";

export const URL_PEC = "http://localhost:8081/lista-atendimento/atendimento/1/soap";

/** Roda na página: a colagem vira blocos do Draft.js (um por linha), no fim do editor. */
function simularDraftJs() {
  document.querySelectorAll<HTMLElement>(".public-DraftEditor-content").forEach((editor) => {
    editor.addEventListener("paste", (evento) => {
      const colado = (evento as ClipboardEvent).clipboardData?.getData("text/plain") ?? "";
      evento.preventDefault();
      const conteudo = editor.querySelector<HTMLElement>('[data-contents="true"]');
      if (!conteudo) return;
      const blocos = [...conteudo.querySelectorAll('[data-block="true"]')].map((b) => b.textContent ?? "");
      const atual = blocos.length === 1 && blocos[0] === "" ? "" : blocos.join("\n");
      conteudo.replaceChildren(
        ...(atual + colado).split("\n").map((linha) => {
          const bloco = document.createElement("div");
          bloco.setAttribute("data-block", "true");
          bloco.textContent = linha;
          return bloco;
        }),
      );
      editor.closest(".DraftEditor-root")?.querySelector(".public-DraftEditorPlaceholder-root")?.remove();
    });
  });
}

/** Abre na aba o atendimento do `paciente` no PEC falso, com o SOAP em branco. */
export async function abrirPecFalso(aba: Page, paciente: PacientePec): Promise<void> {
  const html = htmlPaginaPec({ textos: {}, paciente }).replace(
    "</body>",
    `<script>(${simularDraftJs.toString()})();</script></body>`,
  );
  await aba.route("http://localhost:8081/**", (rota) =>
    rota.fulfill({ contentType: "text/html; charset=utf-8", body: html }),
  );
  await aba.goto(URL_PEC);
}

/** Texto de uma seção do SOAP na tela do PEC, como o Draft.js guarda (um bloco por linha). */
export async function textoDaSecao(aba: Page, testid: string): Promise<string> {
  return aba
    .locator(`[data-testid="${testid}"] [data-block="true"]`)
    .evaluateAll((blocos) => blocos.map((bloco) => bloco.textContent ?? "").join("\n"));
}
