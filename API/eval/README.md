# eval/ — avaliação da IA

`run_eval.py` (B46, **v1**) mede a geração de SOAP contra casos de referência e escreve um relatório markdown.
Especificação: `docs/09-qualidade-testes-avaliacao.md` seção 3 e US022.

## O que a v1 mede

| Métrica | Como | Meta v5.0 |
|---|---|---|
| JSON válido | o SOAP passa no `SoapV1` na 1ª tentativa; há **1 retry** (o motivo da falha vai ao modelo, sem conteúdo) | 100 % com retry |
| Completude | as 4 seções (S, O, A, P) com ≥ 20 palavras cada | ≥ 90 % dos casos |
| Latência | tempo total por caso (soma o retry); p50 e p95 | SOAP p95 ≤ 20 s |
| Custo equivalente | tokens × preço de tabela + minutos de áudio × preço de tabela | informativo (ref. ≤ R$ 0,50 por consulta de 20 min) |

Tudo **por caso e agregado**. WER, acerto de papel, CID-10, alucinação de exame e referências inventadas ficam para a **B57**.
Casos em que o provedor **não respondeu** (cota, chave, timeout) são listados à parte e ficam fora dos agregados.

## Como rodar (a partir de `API/`)

```bash
python eval/run_eval.py --casos tests/fixtures/cases                 # provedor mock, sem chave
python eval/run_eval.py --provedor gemini --casos tests/fixtures/cases --limite 3
python eval/run_eval.py --provedor gemini --estrito                  # sai com 1 se alguma meta falhar
```

Os 20 casos oficiais entram com a **B45** em `eval/cases/` (o padrão do `--casos`). Até lá use `tests/fixtures/cases`
(3 casos de exemplo no mesmo formato).

| Opção | Padrão | Efeito |
|---|---|---|
| `--provedor` | `mock` (ou a variável `EVAL_PROVEDOR`) | `mock` ou `gemini` |
| `--casos` | `eval/cases` | pasta com os `.json` |
| `--saida` | `eval/reports` | pasta dos relatórios |
| `--prompt` | `eval/prompts/soap-provisorio-v1.txt` | o **nome do arquivo** vira a versão do prompt no relatório |
| `--modelo` | `gemini-2.5-flash` | modelo do provedor `gemini` |
| `--pausa` | 0 (mock), 13 s (gemini) | segundos entre casos, por causa do limite por minuto do free tier |
| `--limite` | todos | roda só os N primeiros |
| `--estrito` | desligado | código de saída 1 se alguma meta não for atingida ou algum caso ficar sem resposta |
| `--data` | hoje | `AAAA-MM-DD` do nome do relatório |

Códigos de saída: `0` ok, `1` metas não atingidas (só com `--estrito`), `2` erro de uso (pasta de casos, chave, data...).

## Saída

`eval/reports/AAAA-MM-DD-<provedor>-<prompt_versao>.md` e um `.json` irmão (para comparar relatórios ao trocar prompt ou provedor,
obrigatório antes de mesclar, `docs/09`). Rodar duas vezes no mesmo dia com a mesma combinação **sobrescreve** o arquivo.

O relatório **não contém** texto de caso nem saída do modelo: só métricas, ids e rótulos de erro.
Relatórios do **mock** não são versionados (`eval/.gitignore`): validam o harness, não a IA.

## Provedor Gemini

Usa `GEMINI_API_KEY` do `API/.env` (a chave gratuita de cada desenvolvedor, `docs/12`; **nunca** commitar). Só casos **sintéticos**
podem ser enviados: planos gratuitos podem usar os dados para melhorar modelos. Se a cota estourar (erro 429), o caso aparece como
"sem resposta do provedor" e a execução continua; aumente `--pausa` ou rode com `--limite`.

A API pede JSON puro (`response_mime_type`), mas **não** impõe o esquema, de propósito: a métrica "JSON válido" mede o que o modelo produz.

Tokens vêm do `usage_metadata`. O "pensamento" do 2.5 é cobrado como saída e o SDK fixado (0.8.x) não o expõe: o eval o deriva de `total_token_count - entrada - saída`.

## Custo equivalente

`eval/precos.json` guarda a tabela. **Os valores atuais são ilustrativos** (`"verificado": false`) e o relatório avisa disso.
Antes de usar o número em qualquer decisão, confira a tabela oficial do provedor, atualize e troque para `"verificado": true`
(preenchendo `fonte` e `verificado_em`). O gasto **real** do projeto é R$ 0 (free tier).

## Peças provisórias (saem quando as tarefas chegarem)

- `soap_provisorio.py`: espelha o `SoapV1` da US018 enquanto a **B39** não entrega `soap/schema.py`. O eval tenta importar o oficial
  primeiro; quando ele existir passa a usá-lo sozinho (o relatório diz qual foi usado) e o provisório pode ser apagado.
- `prompts/soap-provisorio-v1.txt`: a **B40** entrega o prompt versionado de produção. Um novo provedor em `run_eval.py`
  (classe com `gerar(caso, erro_anterior)`) encapsula o gerador real sem mexer nas métricas.

## Formato dos casos

Ver `docs/09` seção 3.1. Obrigatórios: `id` e `transcricao` (`[{papel, texto}]`). Opcionais: `prontuario`, `pdfs` (arquivos lidos de
`<casos>/pdfs/`), `gabarito`, `pii_plantada`, `duracao_min` (ou `audio`, um `.wav` de `eval/audio/`) para o custo de áudio.
