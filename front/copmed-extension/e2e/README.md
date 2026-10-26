# E2E da extensão (B56)

Cenário feliz no Chromium com a extensão carregada, contra o backend de verdade:

1. a médica autoriza o microfone e entra pelo popup;
2. cria o paciente que está aberto no e-SUS PEC (falso, na aba) e confere que o popup mostra o nome dele;
3. grava a consulta: o microfone falso do Chromium toca `API/eval/audio/caso-02-infeccao-respiratoria.wav` (B37);
4. o SOAP é gerado e aprovado;
5. o SOAP aprovado é inserido no SOAP do e-SUS PEC e o status vira `inserido_no_pep`.

O que é fixture, e por quê:

- **IA** (chat, SOAP, sugestões): resposta fixa de `fixtures/consulta-infeccao-respiratoria.json`. O CI não tem chave do Gemini, e a qualidade da IA é medida no `eval/`.
- **Transcrição**: o gabarito do áudio, devolvido só se chegou um WAV com som. Se a gravação ou o envio das partes quebrar, o teste falha.
- **e-SUS PEC**: a tela de atendimento dos testes do adaptador (`src/test/esusPecPagina.ts`), servida no endereço do PEC local (`localhost:8081`), onde o content script é injetado.

O resto é o sistema de verdade: popup, background, documento offscreen, content script, rotas, login, banco, anonimização e SOAP. O backend do teste é `API/scripts/servidor_e2e.py`, com banco SQLite próprio e zerado a cada execução.

Limites de hoje:

- Gerar, aprovar e inserir o SOAP ainda não têm tela no popup (SoapEditor, B43). O teste faz, de dentro do popup, a mesma sequência do botão "Inserir no prontuário" (`InsertIntoPepButton.tsx`). Quando o B43 entrar, esses passos viram cliques.
- Só o e-SUS PEC: o Amplimed ainda não recebe o SOAP (B49).

## Rodar na sua máquina (Ubuntu)

A porta 3001 precisa estar livre: pare o backend de desenvolvimento antes.

```bash
# backend (uma vez): o teste usa o venv em API/.venv
cd API
python3 -m venv .venv
.venv/bin/pip install -r requirements-min.txt

# extensão (uma vez)
cd ../front/copmed-extension
npm ci
npx playwright install --with-deps chromium

# teste (faz o build da extensão e sobe o backend do E2E sozinho)
npm run test:e2e
```

Com o Python em outro lugar: `E2E_PYTHON=/caminho/do/python npm run test:e2e`.

Abre uma janela do Chromium durante o teste (uns 15 s): o popup da extensão não funciona sem janela. Sem tela (servidor, CI), rode com `xvfb-run -a npm run test:e2e`.

No CI: workflow `E2E da extensão`, toda noite em `develop` e nos PRs que mexem no E2E. Em caso de falha, o artefato `relatorio-e2e` traz o relatório e os prints do popup e do PEC.
