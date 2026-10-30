# Fixtures HTML dos PEPs

Páginas fictícias usadas pelos testes dos adaptadores (`src/pep/*.test.ts`) e pelo E2E. **Nenhuma contém dado real de paciente.**
Os testes as carregam por `src/test/fixturesPep.ts` e as parseiam com `DOMParser` (jsdom), uma cópia nova por teste.

| Arquivo | Origem | O que representa |
|---|---|---|
| `amplimed-consulta.html` | escrita à mão (B09) | consulta do Amplimed: 8 sinais vitais (`f_prontuario`) e 4 notas (`.note-editable`) |
| `esus-pec-soap-vazio.html` | **gerada** de `htmlPaginaPec` | atendimento do e-SUS PEC, cidadão no cabeçalho e as 4 abas SOAP vazias (só o placeholder) |
| `esus-pec-soap-preenchido.html` | **gerada** de `htmlPaginaPec` | o mesmo, com Subjetivo e Objetivo preenchidos |
| `esus-pec-lista-atendimentos.html` | escrita à mão | outra tela do PEC (lista), com `<header><h2>` e "Nasceu em" **fora** do cabeçalho: nenhum adaptador pode reconhecê-la |
| `pagina-generica.html` | escrita à mão | página que não é PEP (formulário, `textarea` e editor `contenteditable`): ninguém pode reconhecê-la |

## O HTML do e-SUS PEC tem uma fonte só

`htmlPaginaPec` (`src/test/esusPecPagina.ts`) é a fonte do HTML do e-SUS PEC: ele reproduz as abas SOAP do PEC 5.5.28 (`docs/11`) e é usado
por vários testes e pelo E2E (`e2e/pecFalso.ts`). Os dois arquivos **gerados** existem para serem abertos e lidos (no editor ou no navegador),
e `src/pep/fixtures.test.ts` falha se divergirem da fonte. Para regenerá-los depois de mudar `htmlPaginaPec`:

```bash
ATUALIZAR_FIXTURES=1 npx vitest run src/pep/fixtures.test.ts   # grava os arquivos
npx vitest run src/pep/fixtures.test.ts                        # valida (sem a variável)
```

No PowerShell: `$env:ATUALIZAR_FIXTURES=1; npx vitest run src/pep/fixtures.test.ts`.

## Limite de fidelidade (leia antes de confiar)

As fixtures do e-SUS PEC são **derivadas do que o `EsusPecAdapter` procura**, não capturas cruas do sistema. Elas provam que o adaptador lê e
escreve certo nessa estrutura, **não** que o PEC real continua com ela. Se uma atualização do PEC mudar os `data-testid` ou o Draft.js, os testes
seguem verdes e a extensão quebra. Quem protege isso é o teste manual no PEC local (B06/B50). O mesmo vale para o Amplimed: a fixture é a da B09.

Para recapturar do PEC local: salve a tela (cidadão **fictício**), troque nomes por valores de teste, confira que nada de real ficou
(CPF, CNS, telefone) e compare com `esus-pec-soap-vazio.html` antes de atualizar `htmlPaginaPec`.
