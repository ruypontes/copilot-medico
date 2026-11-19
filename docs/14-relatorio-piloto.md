# 14 — Relatório do piloto com médicos (B59)

*Versão parcial de 19/11/2026. Os campos marcados com ☐ serão preenchidos até 22/11 com as sessões da semana. Protocolo: `docs/09` §4. Somente consultas simuladas, sem dado real de paciente (`docs/12` §0).*

## 1. Objetivo

Verificar se um médico consegue, numa consulta simulada, **gravar → revisar o SOAP + CID‑10 → inserir no prontuário** em menos tempo do que escreveria sozinho, e com confiança suficiente para aprovar o registro.

## 2. Participantes e ambiente

| Participante | Perfil | Instalação | Ambiente | Situação |
|---|---|---|---|---|
| Dr. Rui Pontes (PO) | Médico, cliente | 09/11, remota (AnyDesk) pelo Riquelme | Docker local + extensão; Claude Haiku + Whisper/Groq | Instalado |
| Dra. Lorena Mazoni | Médica, cliente desde a v1.0 | 09/11, remota (AnyDesk) pelo Riquelme | Idem; exigiu instalar WSL2 | Instalado, testou e **aprovou** |
| 2ª médica (UBS/SUS) | Médica da atenção primária | ☐ | ☐ | Convite em andamento pelo PO |

**Lição da instalação:** o tempo foi gasto em pré‑requisitos (WSL2, Docker, travamentos do PC), não no CoPilot. Para médicos, a instalação local com Docker é uma barreira; o próximo ciclo deve oferecer o backend hospedado (Render, plano gratuito) e a extensão pela Chrome Web Store.

## 3. Métricas por sessão

| Data | Médico | Caso (id) | Duração da consulta | Tempo até SOAP aprovado | Nº de edições no SOAP | CID‑10 aceito? | Inserido no PEP? | Observação |
|---|---|---|---|---|---|---|---|---|
| 09/11 | Dra. Lorena | livre | ☐ | ☐ | ☐ | ☐ | ☐ | Resposta do chat presa em "digitando" até reabrir |
| ☐ | | | | | | | | |

Meta da v5.0 (`docs/03`): SOAP aprovado em ≤ 2 min após o fim da consulta, com ≤ 3 edições.

## 4. Usabilidade (System Usability Scale)

| Médico | SUS (0–100) | Interpretação |
|---|---|---|
| Dra. Lorena | ☐ | |
| Dr. Rui | ☐ | |

Referência: ≥ 68 é aceitável; ≥ 80 é bom.

## 5. Achados

| # | Achado | Gravidade | Ação | Status |
|---|---|---|---|---|
| A1 | Resposta da IA não aparece; extensão fica em "digitando" até fechar e reabrir. Desconforto visível da médica. | Alta | B72 (#105): mostrar a resposta assim que chega, timeout de 90 s com mensagem clara; streaming no próximo ciclo | Correção em PR |
| A2 | Instalação local exige WSL2/Docker e PC com recursos; travamentos | Média | Backend hospedado gratuito + Chrome Web Store (`docs/10`) | Próximo ciclo |
| A3 | Sem tela de consentimento; consentimento é verbal | Média (LGPD) | B28; texto provisório em `docs/13` parte C | Próximo ciclo |
| A4 | Revisão clínica dos casos de avaliação encontrou erros que ensinariam a IA a não alertar (dengue, tuberculose, dose de ferro e de amoxicilina) | Alta (segurança clínica) | Correções aplicadas nos 20 casos + 4 casos de urgência (B45/B45b) | Aplicado em 19/11 |
| A5 | ☐ achados das sessões de 20–22/11 | | | |

## 6. Entrevista (perguntas fixas)

1. O que mais atrapalhou? ☐
2. Em que parte do SOAP o(a) senhor(a) confiaria sem reler? ☐
3. O que o(a) senhor(a) não usaria de jeito nenhum? ☐
4. Usaria no dia a dia se a instalação fosse feita pela TI? ☐

## 7. Conclusão provisória (PO)

O fluxo central funciona em ambiente real de médico e foi aprovado pela primeira usuária. O maior risco de adesão não é a IA, é **atrito**: espera sem retorno na tela e instalação pesada. Por isso as prioridades do próximo ciclo são resposta em tempo real, modo automático opcional (B71) e instalação sem Docker. Nenhum resultado deste piloto autoriza uso com paciente real: isso depende de RIPD, revisão de segurança (B63) e contrato com provedor de IA que não use os dados para treino.

— Dr. Rui Pontes, Product Owner
