/**
 * Chromium com a extensão carregada para o E2E (B56).
 *
 * - A extensão é a de `dist/` (o `npm run test:e2e` faz o build antes).
 * - O microfone é falso: o Chromium toca um WAV de fixture no lugar da voz, e a
 *   gravação passa pelo caminho real (documento offscreen, partes, envio à API).
 * - O popup é o de verdade, aberto por `chrome.action.openPopup()`. Aberto como
 *   aba ele não serviria: o content script só aceita comandos do popup, e o
 *   popup escreve no PEP da aba ativa da janela dele.
 *
 * O Playwright não se conecta sozinho ao popup de uma extensão. Por isso o
 * Chromium sobe com uma porta de depuração e, depois de o popup abrir, uma
 * segunda conexão (CDP) o enxerga como uma página comum.
 */

import { chromium, type Browser, type BrowserContext, type Page, type Worker } from "@playwright/test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

export const PASTA_EXTENSAO = fileURLToPath(new URL("../dist", import.meta.url));

export class Navegador {
  private conexoes: Browser[] = [];

  private constructor(
    readonly contexto: BrowserContext,
    /** Service worker da extensão (public/background.js). */
    readonly worker: Worker,
    readonly extensaoId: string,
    private readonly perfil: string,
  ) {}

  static async abrir(audioDoMicrofone: string): Promise<Navegador> {
    const perfil = await mkdtemp(join(tmpdir(), "copmed-e2e-chromium-"));
    const contexto = await chromium.launchPersistentContext(perfil, {
      // Só o Chromium completo carrega extensões. Com janela: sem ela (headless) o popup
      // fica mudando de tamanho e os cliques erram. No CI, uma tela virtual (xvfb-run).
      channel: "chromium",
      headless: false,
      args: [
        `--disable-extensions-except=${PASTA_EXTENSAO}`,
        `--load-extension=${PASTA_EXTENSAO}`,
        // Aceita o pedido de microfone sozinho e grava o WAV no lugar da voz.
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        `--use-file-for-fake-audio-capture=${audioDoMicrofone}`,
        // Porta livre escolhida pelo Chromium; ela fica em DevToolsActivePort, no perfil.
        "--remote-debugging-port=0",
      ],
    });
    const worker = contexto.serviceWorkers()[0] ?? (await contexto.waitForEvent("serviceworker"));
    return new Navegador(contexto, worker, new URL(worker.url()).host, perfil);
  }

  url(pagina: string): string {
    return `chrome-extension://${this.extensaoId}/${pagina}`;
  }

  /**
   * Abre o popup sobre a aba `aba` e devolve a página dele. O popup fica preso à
   * janela da aba: é nela que o "Inserir no prontuário" procura o PEP.
   */
  async abrirPopup(aba: Page): Promise<Page> {
    await aba.bringToFront();
    await this.worker.evaluate(() => chrome.action.openPopup());
    const porta = (await readFile(join(this.perfil, "DevToolsActivePort"), "utf8")).split("\n")[0];
    for (let tentativa = 0; tentativa < 50; tentativa++) {
      // Uma conexão nova a cada vez: uma conexão antiga não vê o popup que abriu depois dela.
      const conexao = await chromium.connectOverCDP(`http://127.0.0.1:${porta}`);
      const popup = conexao
        .contexts()
        .flatMap((contexto) => contexto.pages())
        .find((pagina) => pagina.url() === this.url("index.html"));
      if (popup) {
        this.conexoes.push(conexao);
        return popup;
      }
      await conexao.close();
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    throw new Error("O popup da extensão não abriu.");
  }

  async fechar(): Promise<void> {
    await Promise.all(this.conexoes.map((conexao) => conexao.close()));
    await this.contexto.close();
    await rm(this.perfil, { recursive: true, force: true });
  }
}
