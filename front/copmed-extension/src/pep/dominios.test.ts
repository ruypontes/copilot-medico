import { describe, expect, it } from "vitest";
import manifestBruto from "../../public/manifest.json?raw";
import { DOMINIOS_PEP, PADROES_PEP, urlCorrespondeAoPadrao, urlDePep } from "./dominios";

// B51 (US019-CA004 / D-15): o content script não injeta fora dos PEPs suportados.

type Manifest = {
  host_permissions: string[];
  content_scripts: { matches: string[]; js: string[] }[];
};
const manifest = JSON.parse(manifestBruto) as Manifest;
const API = "http://localhost:3001/*";

describe("manifest", () => {
  it("injeta o content script só nos domínios dos PEPs", () => {
    expect(manifest.content_scripts).toHaveLength(1);
    expect(manifest.content_scripts[0].matches).toEqual([...PADROES_PEP]);
  });

  it("não pede acesso a todos os sites", () => {
    const tudo = [...manifest.host_permissions, ...manifest.content_scripts.flatMap((c) => c.matches)];
    for (const padrao of tudo) {
      expect(padrao).not.toBe("<all_urls>");
      expect(padrao).not.toMatch(/^(\*|https?):\/\/\*\//); // *://*/* ou https://*/*
    }
  });

  it("host_permissions = API + domínios dos PEPs", () => {
    expect(manifest.host_permissions).toEqual([API, ...PADROES_PEP]);
  });
});

describe("domínios", () => {
  it.each([
    "https://app.amplimed.com.br/atendimento/123",
    "https://amplimed.com.br/",
    "http://localhost:8081/lista-atendimento",
    "http://127.0.0.1:8081/",
  ])("%s é PEP", (url) => {
    expect(urlDePep(url)).toBe(true);
  });

  it.each([
    "https://www.bb.com.br/",                     // internet banking
    "https://mail.google.com/",
    "http://amplimed.com.br/",                    // Amplimed sem HTTPS
    "https://amplimed.com.br.golpe.com/",         // domínio parecido
    "https://falsoamplimed.com.br/",
    "http://localhost:8080/",                     // copmed-web, não é PEP
    "http://localhost:3001/api/health",           // a própria API
    "chrome://extensions/",
    "texto que não é url",
  ])("%s não é PEP", (url) => {
    expect(urlDePep(url)).toBe(false);
  });

  it("cada PEP tem ao menos um domínio", () => {
    expect(Object.keys(DOMINIOS_PEP)).toEqual(["amplimed", "esus-pec"]);
    for (const padroes of Object.values(DOMINIOS_PEP)) expect(padroes.length).toBeGreaterThan(0);
  });

  it("caminho do padrão também é respeitado", () => {
    expect(urlCorrespondeAoPadrao("https://x.com/app/1", "https://x.com/app/*")).toBe(true);
    expect(urlCorrespondeAoPadrao("https://x.com/outro", "https://x.com/app/*")).toBe(false);
    expect(urlCorrespondeAoPadrao("https://x.com/", "<all_urls>")).toBe(false);
  });
});
