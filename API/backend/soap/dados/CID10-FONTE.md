# Catálogo CID-10 embarcado

Os arquivos `cid10_categories.csv` e `cid10_subcategories.csv` contêm as categorias e subcategorias da CID-10 brasileira, com descrições em português.

- Fonte declarada dos dados: DATASUS / Ministério da Saúde, versão 2008.
- Página de obtenção indicada pela documentação da fonte: http://www2.datasus.gov.br/cid10/V2008/download.htm
- Espelho de distribuição consultado: https://github.com/SidneyBissoli/cid10-br-mcp/tree/master/data
- Estrutura: CSV separado por ponto-e-vírgula, em Windows-1252 (como publicado); lido por `backend/soap/cid10.py`.

Os CSVs são mantidos separados como publicados, e o backend os carrega uma única vez. A tabela serve para consulta de códigos e descrições; não substitui avaliação clínica nem confirma diagnóstico.
