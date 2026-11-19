# 10 — Riscos e decisões pendentes

## Riscos

| ID | Risco | Prob. | Impacto | Sinal de alerta | Mitigação | Dono |
|---|---|---|---|---|---|---|
| R1 | Provedor de transcrição não definido / sem chave paga na Sprint 3 | Alta | Alto | S0 termina sem decisão do PO | Regra dos 72 h (doc 07): vale Gemini áudio com a chave já existente; Vosk como plano B | PO |
| R2 | DOM do Amplimed muda e quebra o adaptador | Média | Médio | Testes de fixture passam mas a página real falha | Fixture atualizada a cada sprint pela conta de teste; seletores com fallback; detecção de "nada extraído" com aviso | TL Front |
| R3 | Sem acesso a conta de teste do Amplimed | Média | Alto | Sprint 1 sem página real | PO consegue conta; enquanto isso, fixture gravada de uma sessão real (sem PII) | PO |
| R4 | e‑SUS PEC local difícil de subir | Média | Médio | Sprint 5 gasta > 2 dias no Docker do PEC | Instalar na Sprint 0 em uma máquina; se falhar até S4, PEC sai do escopo (regra do doc 06) | TL Back |
| R5 | Custo de API estoura | Baixa | Médio | Eval mostra > R$ 0,50/consulta | Chunking, modelo flash, cache de contexto; limite diário por médico | Qualidade |
| R6 | Equipe menor que 6 ou evasão no meio | Média | Alto | Velocidade cai 30 % em duas sprints | Escopo mínimo protegido: Épicos A, B, C, D; E reduz a Amplimed; F reduz a eval automática | SM |
| R7 | Qualidade da diarização insuficiente | Alta | Médio | Papéis < 80 % no eval | Gemini áudio com marcação de falantes; UI para corrigir papel; SOAP não depende do papel | TL Back |
| R8 | Dados reais entram em teste/demo | Baixa | Muito alto | Nome real em fixture, screenshot ou vídeo | Checklist do PR; revisão do responsável por privacidade; vídeos gravados com casos sintéticos | Privacidade |
| R9 | Confusão entre trilha privada e acadêmica | Média | Médio | Alunos tentam integrar Supabase/Vercel | Doc 03 fixa o escopo; ideias da v2.3 entram só como referência | PO |
| R10 | `audioop` / Python 3.13 no computador do aluno | Alta | Baixo | Erro de import na Sprint 0 | README exige 3.11–3.12; Docker resolve | TL Back |
| R11 | Piloto sem médicos disponíveis em dezembro | Média | Médio | Nenhuma agenda confirmada até 04/12 | Confirmar na Sprint 4; plano B: 1 médico + 2 estudantes de medicina | PO |
| R12 | Gemini muda API/SDK durante o semestre | Baixa | Médio | Deprecação anunciada | Camada `llm/provider.py`; versões travadas | TL Back |
| R13 | Instalação inacessível por falta de bootstrap/segredo (D‑22, D‑23) trava a Sprint 0 | Alta | Médio | Onboarding preso em 500/403 | B67: `API/.env.example` + compose com `AUTH_*`; script `bootstrap_admin`; README corrigido em 20/09 | TL Back |

Revisão dos riscos: a cada retrospectiva, o SM atualiza probabilidade/impacto e adiciona novos.

## Decisões do cliente — resolvidas em 15/10/2026

Todas as decisões abaixo foram tomadas pelo PO em **[docs/12-decisoes-po-2026-10-15.md](12-decisoes-po-2026-10-15.md)**, que traz as três opções consideradas em cada ponto, a escolhida e o motivo. Resumo:

| # | Decisão | Resultado | Ação / prazo |
|---|---|---|---|
| P1 | Provedor de transcrição | **Gemini áudio** padrão; Whisper/Groq atrás de `TRANSCRIPTION_PROVIDER=whisper` | B31 primeiro item da S3; B32 por PR própria |
| P2 | Custeio | **Plataformas gratuitas até o primeiro contrato** (AI Studio free, Groq free, GitHub público, Docker local); RNF06 = R$ 0 no semestre | README/.env.example até 23/10 |
| P3 | Segundo PEP | **e‑SUS PEC** (entregue em Docker, PR #71, `docs/11`) | Adaptadores na S5 |
| P4 | Trilha privada | **Congelada até M4**; código da ext. v2.3 só como referência | — |
| P5 | Médicos do piloto | Meta: Rui + Dra. Lorena + médico de UBS; mínimo: Rui + Lorena | PO convida até 20/11 |
| P6 | Repositório | **Público agora** na conta do PO; organização quando o professor confirmar | PO executa 16/10 + proteção de branches |
| P7 | Identificação do paciente | **Opcional e cifrada** (B26) | — |
| P8 | CID‑10 sugerido | **Sim**, confiança qualitativa + busca | — |
| P9 | PEP dos vídeos | **Ambos**; só PEC se não houver conta Amplimed até a S6 | PO: conta até 23/11 |
| P10 | Web app do Grupo 2 (#70) | **(a) manter login, pacientes e aprovação de médicos**; remover placeholders (D‑31) | ADR‑10 em `docs/05`; TL Front até 23/10 |
| P11 | Pacientes legados | **Seed apagado, demais migrados** (B68) | Encerrado |
| P12 | Ordem do áudio | **B31 antes de B32** | S3 |
| P13 | Revisão sem proteção | **Autor nunca mescla a própria PR; 1 aprovação; `Closes #n`** | Vale hoje; CODEOWNERS após P6 |

## Próximo ciclo (registrar desde já)

### Herança da v5.0 (prioridade para o ciclo 6, 2027.1)

| Prioridade | Item | Origem |
|---|---|---|
| 1 | Resposta da IA em tempo real (fim do "digitando" preso) | B72, #105 |
| 2 | Tela de consentimento e registro na consulta | B28, #28 |
| 3 | Modo automático opcional: parar gravação → SOAP pronto para revisar | B71, #107 |
| 4 | Piloto completo: 2 médicos × 10 consultas, SUS e relatório | B58/B59 |
| 5 | `run_eval.py` v2: CID‑10, alucinação, alertas dos casos de urgência | B57 |
| 6 | Exportação PDF/Markdown do SOAP | B55 |
| 7 | Hardening e revisão de segurança antes de qualquer dado real | B63, docs/08 §5 |
| 8 | Deploy gratuito do backend (Render) e publicação na Chrome Web Store | chat da equipe, 11/2026 |

### Ideias para ciclos futuros

- Receitas e atestados com validade legal (assinatura ICP‑Brasil, integração com prescrição eletrônica).
- Terceiro e quarto PEP (iClinic, Tasy) pelo padrão de adaptador.
- Whisper local em GPU para eliminar envio de áudio.
- Publicação na Chrome Web Store com política de privacidade.
- RIPD e parecer jurídico para uso clínico rotineiro.
- Histórico pesquisável por palavra‑chave (US009 original).
