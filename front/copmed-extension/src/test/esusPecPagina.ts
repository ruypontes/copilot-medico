/**
 * Página fictícia do e-SUS APS PEC para os testes do EsusPecAdapter (B50).
 *
 * A estrutura copia a tela de atendimento (aba SOAP) do PEC 5.5.28 rodando
 * localmente: cabeçalho do cidadão e os editores Draft.js de cada seção,
 * com os mesmos `data-testid`, ids e classes do Draft.js. As classes
 * geradas (`css-*`), a barra de ferramentas e os blocos fora do SOAP
 * foram omitidos. Dados 100% fictícios.
 */

const SECOES = [
  { letra: "S", titulo: "Subjetivo", testid: "textFieldSubjetivo", dica: "Insira as impressões subjetivas do profissional e as expressadas pelo cidadão." },
  { letra: "O", titulo: "Objetivo", testid: "observacoesObjetivo", dica: "Insira as demais informações relacionadas ao exame físico." },
  { letra: "A", titulo: "Avaliação", testid: "TextFieldObservacaoAvaliacao", dica: "Insira impressões adicionais sobre a avaliação dos problemas/condições detectados." },
  { letra: "P", titulo: "Plano", testid: "textFieldPlano", dica: "Insira informações adicionais sobre o plano de cuidado." },
] as const;

const escapar = (texto: string) =>
  texto.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** Blocos do Draft.js: um por linha; linha vazia vira `<br data-text>`. */
function blocosDraft(chave: string, texto: string): string {
  return texto
    .split("\n")
    .map((linha, i) => {
      const offset = `${chave}-${i}-0`;
      const conteudo = linha
        ? `<span data-offset-key="${offset}"><span data-text="true">${escapar(linha)}</span></span>`
        : `<span data-offset-key="${offset}"><br data-text="true"></span>`;
      return `<div data-block="true" data-editor="${chave}" data-offset-key="${offset}"><div class="public-DraftStyleDefault-block public-DraftStyleDefault-ltr" data-offset-key="${offset}">${conteudo}</div></div>`;
    })
    .join("");
}

function secaoSoap(secao: (typeof SECOES)[number], texto: string): string {
  const chave = `ed${secao.letra}`;
  const placeholder = texto
    ? ""
    : `<div class="public-DraftEditorPlaceholder-root"><div class="public-DraftEditorPlaceholder-inner" id="placeholder-${chave}">${secao.dica}</div></div>`;
  return `
    <div data-accordion-component="AccordionItem" class="accordion__item">
      <div role="button" tabindex="0">
        <div role="button" data-accordion-component="AccordionItemButton" id="accordion__heading-${secao.letra}" aria-expanded="true" aria-controls="accordion__panel-${secao.letra}">
          <div><span>${secao.letra}</span><h2>${secao.titulo}</h2></div>
        </div>
      </div>
      <div data-accordion-component="AccordionItemPanel" class="accordion__panel" aria-hidden="false" aria-labelledby="accordion__heading-${secao.letra}" id="accordion__panel-${secao.letra}">
        <div data-testid="${secao.testid}">
          <div>
            <div class="RichTextEditor__root___2QXK-">
              <div class="EditorToolbar__root___3_Aqz"><button type="button" title="Negrito">B</button></div>
              <div class="RichTextEditor__editor___1QqIU">
                <div class="DraftEditor-root">
                  ${placeholder}
                  <div class="DraftEditor-editorContainer">
                    <div aria-describedby="placeholder-${chave}" aria-label="${secao.dica}" class="notranslate public-DraftEditor-content" contenteditable="true" role="textbox" spellcheck="true">
                      <div data-contents="true">${blocosDraft(chave, texto)}</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <span>${texto.replace(/\n/g, "").length}/4000 caracteres</span>
      </div>
    </div>`;
}

export interface OpcoesPaginaPec {
  /** Texto já presente em cada seção (por padrão, só o Objetivo tem texto). */
  textos?: Partial<Record<"S" | "O" | "A" | "P", string>>;
  /** Sem o simulador, a colagem não é tratada: imita o Draft.js recusando o texto. */
  semDraft?: boolean;
  /** Cidadão do cabeçalho; `null` tira o cabeçalho do cidadão (o SOAP continua na tela). */
  paciente?: PacientePec | null;
}

export type PacientePec = { nome: string; sexo: string; idade: string };

export const PACIENTE_PEC: PacientePec = { nome: "Paciente Fictício Copmed", sexo: "Feminino", idade: "38 anos e 2 meses" };

/** Sem espaço entre as tags, como no PEC: o texto sai colado ("Feminino38 anos"). */
function cabecalhoCidadao({ nome, sexo, idade }: PacientePec): string {
  return `<div><div><div><div><h2>${escapar(nome)}</h2></div><div><span>| Sexo ${sexo}</span></div></div></div><div><div><div><div><div><span>${idade}| Nasceu em <time>15/08/1988</time></span></div></div></div></div><div><p><span>CPF</span><span>—</span></p><p><span>CNS</span><span>—</span></p></div></div></div>`;
}

export function htmlPaginaPec({
  textos = { O: "PA 120/80 mmHg.\nAfebril." },
  paciente = PACIENTE_PEC,
}: OpcoesPaginaPec = {}): string {
  return `<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>PEC</title></head>
<body>
  <header>
    ${paciente ? cabecalhoCidadao(paciente) : ""}
    <nav>
      <a href="/lista-atendimento/atendimento/1/folha-rosto">Folha de rosto</a>
      <a href="/lista-atendimento/atendimento/1/soap" aria-current="page">SOAP</a>
      <a href="/lista-atendimento/atendimento/1/historico">Histórico</a>
    </nav>
  </header>
  <main>
    <div data-accordion-component="Accordion">
      ${SECOES.map((secao) => secaoSoap(secao, textos[secao.letra] ?? "")).join("\n")}
    </div>
  </main>
</body></html>`;
}

/**
 * Faz o papel do Draft.js na colagem: cancela o evento e acrescenta o
 * texto colado ao fim do editor, refazendo os blocos (um por linha).
 */
function simularDraft(page: Document): void {
  page.querySelectorAll<HTMLElement>(".public-DraftEditor-content").forEach((editor) => {
    editor.addEventListener("paste", (evento) => {
      const colado = (evento as ClipboardEvent).clipboardData?.getData("text/plain") ?? "";
      evento.preventDefault();
      const blocos = [...editor.querySelectorAll('[data-block="true"]')].map((b) => b.textContent ?? "");
      const atual = blocos.length === 1 && blocos[0] === "" ? "" : blocos.join("\n");
      const chave = editor.querySelector("[data-editor]")?.getAttribute("data-editor") ?? "ed";
      const conteudo = editor.querySelector('[data-contents="true"]') as HTMLElement;
      conteudo.innerHTML = blocosDraft(chave, atual + colado);
      editor.closest(".DraftEditor-root")?.querySelector(".public-DraftEditorPlaceholder-root")?.remove();
    });
  });
}

export function criarPaginaPec(opcoes: OpcoesPaginaPec = {}): Document {
  const page = new DOMParser().parseFromString(htmlPaginaPec(opcoes), "text/html");
  if (!opcoes.semDraft) simularDraft(page);
  return page;
}

/** Texto do Subjetivo, lido dos blocos do Draft.js. */
export function lerSubjetivoPec(page: Document): string | null {
  const editor = page.querySelector('[data-testid="textFieldSubjetivo"] [contenteditable="true"]');
  if (!editor) return null;
  return [...editor.querySelectorAll('[data-block="true"]')].map((b) => b.textContent ?? "").join("\n");
}
