/**
 * Domínios dos PEPs suportados (B51 / US019-CA004 / D-15).
 *
 * O content script só é injetado nestes endereços, nunca em `<all_urls>`. O
 * `public/manifest.json` repete esta lista em `content_scripts.matches` e em
 * `host_permissions`; o teste `dominios.test.ts` falha se os dois divergirem.
 *
 * - Amplimed: sistema web em `*.amplimed.com.br` (só HTTPS).
 * - e-SUS PEC: instalado por município, cada um com seu endereço. A lista traz
 *   a instalação local de desenvolvimento (docs/11-esus-pec.md: porta 8081 no
 *   host). Um município novo entra aqui e no manifest.
 */

export const DOMINIOS_PEP: Record<string, readonly string[]> = {
  amplimed: ["https://*.amplimed.com.br/*"],
  "esus-pec": ["http://localhost:8081/*", "http://127.0.0.1:8081/*"],
};

/** Todos os padrões, na ordem acima: é o que vai para o manifest. */
export const PADROES_PEP: readonly string[] = Object.values(DOMINIOS_PEP).flat();

/**
 * Confere uma URL contra um match pattern do Chrome (`esquema://host/caminho`),
 * com `*` no início do host valendo para o domínio e seus subdomínios. Basta
 * para os padrões acima; não cobre `<all_urls>` de propósito.
 */
export function urlCorrespondeAoPadrao(url: string, padrao: string): boolean {
  const partes = /^(https?|\*):\/\/([^/]+)(\/.*)$/.exec(padrao);
  if (!partes) return false;
  let alvo: URL;
  try {
    alvo = new URL(url);
  } catch {
    return false;
  }
  const [, esquema, host, caminho] = partes;
  const esquemaAlvo = alvo.protocol.slice(0, -1);
  if (esquema === "*" ? !["http", "https"].includes(esquemaAlvo) : esquema !== esquemaAlvo) return false;

  // O host do padrão pode ter porta ("localhost:8081"); `alvo.host` também.
  if (host.startsWith("*.")) {
    const dominio = host.slice(2);
    if (alvo.host !== dominio && !alvo.host.endsWith(`.${dominio}`)) return false;
  } else if (alvo.host !== host) {
    return false;
  }

  const regexCaminho = new RegExp(`^${caminho.split("*").map(escapar).join(".*")}$`);
  return regexCaminho.test(alvo.pathname + alvo.search);
}

function escapar(texto: string): string {
  return texto.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** A URL é de um PEP suportado? */
export function urlDePep(url: string): boolean {
  return PADROES_PEP.some((padrao) => urlCorrespondeAoPadrao(url, padrao));
}
