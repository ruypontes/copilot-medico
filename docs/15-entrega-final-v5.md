# 15 — Entrega final da v5.0 (23/11/2026): roteiro dos vídeos, relatório técnico e checklist de release

*B65 e B66. Preparado pelo PO em 19/11 para a equipe gravar e apresentar na segunda‑feira.*

## 1. Checklist até 23/11

| # | Item | Dono sugerido | Prazo | Issue |
|---|---|---|---|---|
| 1 | Regularizar a cobrança da conta no GitHub para o Actions voltar a rodar | PO | 20/11 | — |
| 2 | Revisar e mesclar a PR da B72 (resposta da IA) | Riquelme ou Rafael | 20/11 | #105 |
| 3 | Revisar e mesclar a PR de entregas do PO (casos B45/B45b + docs 13–15 + CHANGELOG) | Gabriel ou Alter | 20/11 | #45, #59, #64 |
| 4 | Rodar `run_eval.py` com os casos corrigidos (Claude e Gemini) e anexar o relatório | Alter | 21/11 | #46 |
| 5 | Sessões de piloto: Dr. Rui e Dra. Lorena (mínimo 3 casos cada) e preencher `docs/14` | Riquelme + PO | 22/11 | #58, #59 |
| 6 | Capturas de tela do `docs/13` | Vinícius | 21/11 | #64 |
| 7 | Gravar os dois vídeos (seção 2) | Vinícius + Riquelme | 22/11 | #65 |
| 8 | Slides da apresentação (seção 3) | Vinícius | 22/11 | #65 |
| 9 | Merge `develop` → `main`, tag `v5.0.0`, release com `dist.zip` da extensão | Riquelme | 23/11 | #66 |

## 2. Roteiro dos vídeos (padrão REACT Labs)

Só casos sintéticos (`API/eval/cases`). Nenhum dado real na tela. Feche abas com e‑mail e outras contas antes de gravar.

### Vídeo 1 — Amplimed (≈ 4 min)

| Tempo | Cena | Fala (resumo) |
|---|---|---|
| 0:00–0:30 | Slide‑título e problema | "O médico gasta até metade da consulta escrevendo. A v5.0 transforma a conversa em prontuário." |
| 0:30–1:00 | Login na extensão, seleção do paciente sintético | Autenticação, isolamento por médico |
| 1:00–1:20 | Leitura do texto de consentimento (`docs/13` C2) | LGPD na prática |
| 1:20–2:20 | Gravação do **caso 04** (amigdalite) com dois membros como médico e paciente | Pausar/retomar; popup fechado e gravação continua |
| 2:20–3:20 | Parar → Gerar SOAP → CID‑10 J03.9 → pendências → editar uma linha → Aprovar | O médico decide; versões guardadas |
| 3:20–3:50 | Inserir no prontuário Amplimed | `PepAdapter` |
| 3:50–4:00 | Encerramento | "Nada entra no prontuário sem o médico aprovar." |

### Vídeo 2 — e‑SUS PEC e segurança clínica (≈ 4 min)

| Tempo | Cena | Fala (resumo) |
|---|---|---|
| 0:00–0:20 | e‑SUS PEC local no Docker | O prontuário do SUS, sem custo |
| 0:20–1:30 | **Caso u01** (dor torácica): o médico simulado subestima o quadro | O CoPilot alerta SCA e encaminhamento |
| 1:30–2:30 | SOAP com alerta → aprovar → conferência de paciente → inserir no e‑SUS PEC | Paciente trocado é bloqueado |
| 2:30–3:20 | Anonimização: payload enviado à IA sem nome, CPF e telefone (painel de debug ou log) | Pseudonimização reversível local |
| 3:20–4:00 | Relatório do `run_eval.py` e próximos passos | Métrica, não opinião |

## 3. Estrutura da apresentação (10 slides, 10 min)

1. Problema e público (médico da atenção primária)
2. Histórico dos 5 ciclos (`docs/01`)
3. Objetivo da v5.0: da conversa ao prontuário
4. Arquitetura: extensão + Flask + Postgres + provedores com reserva (`docs/05`)
5. Demonstração (vídeo 1, trecho)
6. LGPD: anonimização, áudio apagado, isolamento, consentimento (`docs/08`)
7. Qualidade: testes, eval com 24 casos revisados por médico, piloto (`docs/09`, `docs/14`)
8. Processo: sprints, revisão de PR, decisões do PO (`docs/12`)
9. O que ficou para o ciclo 6 (`docs/10`)
10. Agradecimentos e equipe

## 4. Relatório técnico (resumo para o Classroom)

**Produto.** Extensão Chrome (React/TS, MV3) que grava a consulta, transcreve (Whisper/Groq; Gemini áudio e Vosk como alternativas), anonimiza, gera SOAP estruturado com CID‑10 (Claude Haiku 5.5 com Gemini de reserva) e escreve no prontuário (Amplimed e e‑SUS PEC) depois da aprovação do médico.

**Arquitetura.** Backend Flask com SQLAlchemy/Alembic (Postgres em Docker), JWT com refresh, repositórios por entidade, provedores de IA atrás de interfaces (`TranscriptionProvider`, `LlmProvider` com reserva), `PepAdapter` + registry na extensão. Decisões em ADR‑01 a ADR‑10.

**Privacidade.** Pseudonimização regex + NER com mapa criptografado local; testes automáticos de vazamento de PII; áudio apagado após transcrição; CORS por origem; cada médico só vê os próprios pacientes.

**Qualidade.** Suíte pytest e Vitest, contratos de PEP, E2E Playwright escrito; `run_eval.py` com 20 casos de atenção primária e 4 de urgência, gabaritos revisados por médico.

**Limitações.** GitHub Actions bloqueado por cobrança na conta durante parte do semestre; piloto com uma médica; consentimento ainda verbal; uso clínico real depende de RIPD, revisão de segurança e contrato de IA sem uso dos dados para treino.

**Próximo ciclo.** Ver `docs/10`, seção "Herança da v5.0".

## 5. Release v5.0.0 (B66)

```bash
git checkout main && git pull
git merge --no-ff develop -m "release: v5.0.0"
git tag -a v5.0.0 -m "CoPilot Médico v5.0.0 — Da conversa ao prontuário"
git push origin main v5.0.0
cd front/copmed-extension && npm ci && npm run build && (cd dist && zip -r ../copmed-extension-v5.0.0.zip .)
gh release create v5.0.0 front/copmed-extension/copmed-extension-v5.0.0.zip -F CHANGELOG.md --title "v5.0.0"
```

A release **não** inclui `.env`, chaves, áudios reais ou bancos de dados.

— Dr. Rui Pontes, Product Owner
