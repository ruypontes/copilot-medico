import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

// E2E da extensão (B56): Chromium com a extensão de dist/ carregada, contra o backend
// de verdade com a IA trocada por fixture (API/scripts/servidor_e2e.py). Ver e2e/README.md.
const PASTA_API = fileURLToPath(new URL("../../API", import.meta.url));
const FIXTURE = fileURLToPath(new URL("./e2e/fixtures/consulta-infeccao-respiratoria.json", import.meta.url));
// Python do backend: E2E_PYTHON, ou o venv em API/.venv, ou o python3 do sistema (CI).
const PYTHON =
  process.env.E2E_PYTHON || (existsSync(`${PASTA_API}/.venv/bin/python`) ? ".venv/bin/python" : "python3");

export default defineConfig({
  testDir: "e2e",
  // Um Chromium com a extensão e um backend com banco próprio: nada roda em paralelo.
  workers: 1,
  timeout: 120_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [["list", { printSteps: true }], ["html", { open: "never" }]]
    : [["list", { printSteps: true }]],
  webServer: {
    command: `${PYTHON} scripts/servidor_e2e.py --fixture "${FIXTURE}"`,
    cwd: PASTA_API,
    // A extensão chama a API em localhost:3001 (VITE_API_URL padrão e host_permissions).
    url: "http://127.0.0.1:3001/api/health",
    // Nunca o backend de desenvolvimento que já estiver na 3001: o teste cria médica e paciente.
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "pipe",
  },
});
