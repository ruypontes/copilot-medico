# 13 — Guia de instalação e manual do médico (v5.0)

*Versão de 19/11/2026 (branch `develop`). Substitui o `guia-instalacao-copilot-medico.docx` de 05/11, que fica como histórico.*

Este guia parte do zero: o projeto acabou de ser baixado do GitHub. No fim, a API, o banco e o painel web estarão rodando no Docker e a extensão estará instalada no Chrome. A **parte A** é para quem instala (equipe ou TI). A **parte B** é para o médico. A **parte C** é o termo de consentimento do paciente.

> **Regra de ouro (docs/12):** enquanto o projeto usa planos gratuitos de IA, **nenhum dado real de paciente** entra no sistema. Piloto só com consultas simuladas.

---

## Parte A — Instalação

### A0. O que vem no projeto

| Parte | Para que serve | Onde roda |
|---|---|---|
| API (backend Flask) | Guarda pacientes e consultas, anonimiza, transcreve e conversa com a IA | Docker, `http://localhost:3001` |
| Banco de dados | PostgreSQL 16 com todos os dados | Docker, só nesta máquina |
| Painel web (`copmed-web`) | Login, pacientes e aprovação de médicos pelo administrador | Docker, `http://localhost:8080` |
| Extensão do Chrome | Ferramenta do médico na consulta: gravação, chat, sugestões, SOAP + CID‑10 e envio ao prontuário | Google Chrome |
| e‑SUS PEC (opcional) | Prontuário do SUS para testes locais | Docker, perfil `esus`, `http://localhost:8081` |

### A1. Pré‑requisitos

1. Windows 10/11 com **Docker Desktop** (WSL2) aberto em "Engine running". Linux e macOS também funcionam.
2. **Google Chrome.**
3. **Node.js 20+** para compilar a extensão (`node --version`).
4. **Chaves de IA** (todas têm plano gratuito, exceto a da Anthropic, fornecida pelo PO):

| Variável | Para quê | Onde obter | Obrigatória? |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Claude Haiku 5.5: chat, sugestões e SOAP (provedor **padrão**) | console.anthropic.com | Sim, ou a do Gemini |
| `GEMINI_API_KEY` | Gemini: **reserva** do chat e transcrição alternativa | aistudio.google.com/apikey | Recomendada |
| `GROQ_API_KEY` | Whisper large‑v3 via Groq: transcrição **padrão** | console.groq.com/keys | Recomendada |

5. **15 GB livres** no disco C: (imagens do Docker).

### A2. Extrair e configurar

1. Extraia o `.zip` numa pasta sem acentos nem espaços (ex.: `C:\Projetos\`) e abra um **PowerShell** nela.
2. Copie o modelo de configuração:

```powershell
Copy-Item API\.env.example API\.env
```

3. Gere **dois** segredos (rode duas vezes):

```powershell
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b).Replace('+','x').Replace('/','y').Replace('=','')
```

4. Abra `notepad API\.env` e preencha:

| Campo | O que colocar |
|---|---|
| `ANTHROPIC_API_KEY` | Chave da Anthropic |
| `LLM_PROVIDER` | `claude` (padrão) ou `gemini` |
| `GEMINI_API_KEY` | Chave do Google AI Studio |
| `TRANSCRIPTION_PROVIDER` | `whisper` (padrão), `gemini` (separa médico e paciente) ou `vosk` (local, sem enviar áudio) |
| `GROQ_API_KEY` | Chave da Groq (para `whisper`) |
| `AUTH_SECRET_KEY` | Primeiro segredo |
| `AUTH_BOOTSTRAP_EMAIL` / `AUTH_BOOTSTRAP_PASSWORD` | Login do administrador inicial |
| `POSTGRES_PASSWORD` | Segundo segredo |
| `DB_URL` | Troque `<senha-do-postgres>` pelo **mesmo** segundo segredo |

> **Segurança das chaves.** O `API/.env` nunca vai para o Git, para zip, para Drive nem para print. Cada instalação usa suas próprias chaves. Se uma chave vazar, **revogue e gere outra** no painel do provedor no mesmo dia.
>
> **Não altere** `CORS_ORIGINS`. Com `*`, o painel web não faz login ("Failed to fetch").

### A3. Subir o sistema

```powershell
docker compose up -d --build
```

A primeira vez leva 5–15 min. Confira:

1. `http://localhost:3001/api/health` mostra `"status": "success"`.
2. `http://localhost:8080` mostra o login do painel.

Para incluir o e‑SUS PEC local: `docker compose --profile esus up -d` (detalhes em `docs/11-esus-pec.md`).

### A4. Administrador e médicos

1. Em `http://localhost:8080`, entre com o `AUTH_BOOTSTRAP_*`, perfil **Administrador**.
2. O médico se cadastra em **Cadastrar médico**; a conta fica **pendente**.
3. O administrador abre **Médicos → Pendentes → Aprovar**.

### A5. Compilar e instalar a extensão

```powershell
cd front\copmed-extension
npm install
npm run build
```

No Chrome: `chrome://extensions` → **Modo do desenvolvedor** → **Carregar sem compactação** → pasta `front\copmed-extension\dist` → fixe a "Copmed Extension" na barra.

A extensão só tem permissão para a API local, o Amplimed e o e‑SUS PEC local.

### A6. Ligar, desligar, atualizar

| Ação | Comando |
|---|---|
| Desligar mantendo dados | `docker compose stop` |
| Ligar | `docker compose start` |
| Atualizar | `git pull` (ou novo zip) → `docker compose up -d --build` → `npm install && npm run build` na extensão → **↻** em `chrome://extensions` |

---

## Parte B — Manual do médico

### B1. Antes da consulta

1. Clique no ícone da extensão e entre com seu e‑mail e senha (perfil **Médico**).
2. Em **Selecione um Paciente**, escolha ou crie o paciente.
3. Crie a consulta em **Nova Consulta** (ou escolha uma existente).
4. **Peça o consentimento do paciente para gravar** (parte C). Sem consentimento, não grave: use só o chat.

### B2. Durante a consulta

| Função | Como usar | Observação |
|---|---|---|
| **Gravar** | **Iniciar gravação** → autorize o microfone na 1ª vez → **Pausar / Retomar / Parar** | Pode fechar o popup; a gravação continua (até 120 min). O áudio é apagado do servidor após a transcrição. |
| **Sugestões** | Painel **Sugestões** → escolha a janela em minutos | Até 5 itens curtos (perguntas, exames, diferenciais, alertas). Não vão para o prontuário. |
| **Chat** | Escreva em "Digite sua mensagem..." | Nome, CPF, telefone e endereço são **anonimizados** antes de sair para a IA. |
| **PDF** | Ícone **Enviar PDF** no chat | Exames e laudos; texto anonimizado antes da IA. |
| **Dados do prontuário** | Botão flutuante **"Copilot: enviar dados do prontuário"** no Amplimed ou e‑SUS PEC | Se o paciente do PEP for diferente do da extensão, a extensão **bloqueia** e pede confirmação. |

### B3. Depois da consulta — SOAP e CID‑10

1. Clique em **Parar** e depois em **Gerar SOAP**.
2. Revise as quatro seções (Subjetivo, Objetivo, Avaliação, Plano) e o **CID‑10 sugerido**. Use a busca de CID‑10 para trocar o código.
3. Leia as **pendências e alertas**: o que a IA percebeu que faltou perguntar, examinar ou registrar.
4. Edite o que for preciso e clique em **Aprovar**. Cada edição gera uma nova versão; nada é sobrescrito.
5. Com o atendimento aberto no PEP, clique em **Inserir no prontuário**. No e‑SUS PEC há uma conferência do paciente antes de escrever.

> **Responsabilidade clínica.** O CoPilot é um **assistente**. O SOAP só vale depois que o médico revisa e aprova. A IA pode errar dose, omitir alerta ou registrar algo que não foi dito: confira sempre, principalmente medicação e sinais de alarme.

### B4. Problemas comuns

| Sintoma | O que fazer |
|---|---|
| Resposta da IA fica em **"digitando"** | Problema conhecido (issue #105, em correção). Feche e reabra o popup da extensão; a resposta aparece. |
| "Failed to fetch" no painel | `CORS_ORIGINS` voltou para `*`: restaure o padrão e rode `docker compose up -d --force-recreate backend` |
| Ninguém consegue entrar | `AUTH_BOOTSTRAP_*` vazio no 1º start: preencha e recrie o backend |
| Banco não sobe | `POSTGRES_PASSWORD` vazia ou diferente da senha em `DB_URL` |
| IA responde com erro | Chave errada ou cota gratuita esgotada (429). Com Claude como padrão, o Gemini assume como reserva. |
| Médico não entra | Cadastro pendente: o administrador aprova em **Médicos** |
| "Validando sessão..." eterno | A extensão foi aberta como página comum. Use pelo ícone. |
| Gravação não começa | Permissão do microfone negada: autorize nas configurações do site |
| Botão flutuante não aparece | Abra o atendimento (aba SOAP) e confira a permissão do site em `chrome://extensions → Detalhes` |
| Docker cai no build (SIGBUS) | Disco cheio: libere espaço e rode `docker builder prune -f` |

---

## Parte C — Consentimento do paciente para gravação

### C1. Quando pedir

**Antes** de iniciar a gravação, em toda consulta. O registro do consentimento (sim/não, data e hora, médico) fica na consulta. Recusa não prejudica o atendimento: o médico segue sem gravar.

### C2. Texto para ler ao paciente

> "Eu uso um assistente de computador que grava o áudio da nossa conversa para me ajudar a escrever o seu prontuário. Antes de ir para a inteligência artificial, seu nome, CPF, telefone e endereço são retirados. O áudio é apagado logo depois de virar texto. Eu reviso tudo antes de salvar no seu prontuário. O(a) senhor(a) autoriza a gravação? Pode recusar sem nenhum prejuízo ao seu atendimento, e pode pedir para parar a qualquer momento."

### C3. O que o sistema garante (LGPD — docs/08)

| Garantia | Como |
|---|---|
| Finalidade | Só para gerar o registro clínico da consulta (art. 11, II, *f* — tutela da saúde) |
| Minimização | Dados identificáveis são pseudonimizados antes de qualquer envio externo; o mapa de pseudônimos é criptografado e fica local |
| Retenção do áudio | Apagado após a transcrição; partes órfãs apagadas em até 24 h |
| Isolamento | Cada médico vê só os próprios pacientes |
| Revogação | O paciente pode pedir para parar; o médico interrompe a gravação |
| Dados reais | **Proibidos** enquanto o projeto usar planos gratuitos de IA (docs/12, §0) |

### C4. Pendência registrada

A tela de consentimento dentro da extensão (B28, issue #28) **ainda não foi implementada**. Até lá, o consentimento é verbal, com o texto da seção C2, e o médico anota "consentimento verbal para gravação" no Subjetivo.

— Revisado pelo PO, Dr. Rui Pontes, 19/11/2026
