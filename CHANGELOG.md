# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versões seguem SemVer.

## [5.0.0] — 2026-11-23 · "Da conversa ao prontuário" (ciclo 5, 2026.2)

Entregue pela Equipe 5 de Engenharia de Software (UPE/POLI, REACT Labs). PO: Dr. Rui Pontes.

### Adicionado
- **SOAP estruturado** (`SoapV1`, pydantic) gerado a partir da consulta, com prompt em PT‑BR e saída validada (B39, B40), versões a cada edição (B44) e avaliação automática (B46, `eval/run_eval.py`).
- **Editor de SOAP na extensão** com busca na tabela CID‑10 embarcada, aprovação e botão **Inserir no prontuário** (B42, B43).
- **Escrita no prontuário** pelo padrão `PepAdapter` + registry: Amplimed (B49) e **e‑SUS PEC** (B50), com conferência de paciente trocado (B51–B53) e e‑SUS PEC 5.5.28 em Docker (B06, perfil `esus`).
- **Transcrição por provedor configurável** (`TRANSCRIPTION_PROVIDER`): Whisper large‑v3 via Groq (padrão, B32), Gemini áudio com marcação de falantes (B31) e diarizador local Vosk como fallback (`vosk`).
- **Gravação fora do popup** com pausar/retomar/parar, cronômetro, limite de 120 min e upload em partes de 5 min (B29, B30); áudio apagado após a transcrição e job de limpeza (B35).
- **Sugestões sobre a janela recente** da consulta (B38).
- **LLM com reserva**: Claude Haiku 5.5 como padrão e Gemini como reserva (`LLM_PROVIDER`, `ProvedorComReserva`); migração para `google-genai` (B41).
- **Anonimização** por regex + NER com mapa de pseudônimos criptografado (B25, B26, B69) e testes de vazamento de PII (B47, B60).
- **Banco relacional**: modelos SQLAlchemy + Alembic, repositórios por entidade e migração dos JSON legados (B19, B20, B21, D‑24).
- **Autenticação** com refresh token, política de senha, rate limit e bloqueio (B22); sessão em `storage.session` na extensão e na web (B27).
- **Docker Compose** com Postgres, backend e painel web; download de modelos (B12, #80).
- **CI** do frontend e da API e proteção de branches (B11); teste E2E Playwright do cenário feliz escrito (B56).
- **Casos de avaliação**: 20 casos sintéticos revisados clinicamente (B45) e 4 casos de urgência (B45b); 10 áudios sintéticos de referência (B37).
- Documentação: `docs/00–13`, guia de instalação e manual do médico com termo de consentimento (`docs/13`).

### Alterado
- `App.tsx` da extensão dividido em features (B17).
- Repositório principal **público** desde 15/11/2026 (P6); trabalho integrado no repositório principal (issue #106).

### Segurança
- Histórico reescrito para remover chaves vazadas dos ciclos anteriores; varredura completa limpa antes da abertura.
- Upload e logs de debug sem conteúdo clínico (#123); CORS restrito por origem; admin criado por bootstrap.

### Problemas conhecidos
- Resposta da IA pode ficar em "digitando" até reabrir o popup (B72, #105).
- Tela de consentimento na extensão (B28), exportação PDF/Markdown do SOAP (B55), auditoria de envios externos (B36), provider Vosk na interface nova (B33) e métricas avançadas do eval (B57) ficam para o próximo ciclo.
- GitHub Actions bloqueado por pendência de cobrança na conta: os workflows existem, mas não executam até a regularização.
- Piloto com uma médica concluído; segunda médica em agendamento (B58).

## [4.0.0] — 2026.1 · Grupo 2
Autenticação por perfil (scrypt + JWT), aprovação de médicos, sistema gerenciador web, rota `extension/extracted-data`.

## [3.0.0] — 2025.2 · Equipe 6
Gravação de áudio, diarização Vosk + Google SR, rota de recomendações, Docker, testes.

## [2.0.0] — 2025.1 · Equipe 4
Gemini, anonimização spaCy, upload de PDF, banco JSON, histórico por consulta.

## [1.0.0] — 2024.2 · Equipe 3
Extensão Chrome + Flask + GPT‑4 sobre o Amplimed.
