# 16 — Modelo econômico: B2C, B2B e B2G

*Preparado pelo PO em 20/11/2026. Apresentação: <https://claude.ai/artifact/P7uEbmXFH7sq3iyJ7qHy1P> (privada; peça acesso ao PO). Preços, margens e projeção são propostas e estimativas do PO; os dados de mercado têm fonte na seção 8.*

## 1. Recomendação

Modelo híbrido com o **B2G como tese principal**: vender primeiro para a atenção primária do SUS, por equipe de Saúde da Família, escrevendo no e‑SUS PEC. O B2C freemium entra como motor de evidência e de marca. O B2B só entra por parceria de marca branca com fornecedores de prontuário que ainda não têm IA.

Motivo: é o único dos três mercados em que o diferencial do CoPilot (adaptador e‑SUS PEC, anonimização local, origem universitária) vale mais do que capital de marketing.

## 2. Estudo de mercado

**Dor.** Estudos dos EUA apontam cerca de 2 h de prontuário para cada 1 h de atendimento. No Brasil, 62% dos médicos já tiveram burnout e 27% se dizem exauridos pela burocracia (Afya, 2022). O ganho medido da IA de documentação é modesto: 8 a 10% menos tempo de registro em estudos de 2025 (JAMA Network Open; NEJM AI). Não prometer 40%. Não há dado brasileiro de minutos de prontuário por consulta; o piloto precisa produzi‑lo.

**Tamanho.**

| Indicador | Valor | Fonte |
|---|---|---|
| Médicos no Brasil (projeção 2025) | 635,7 mil | Demografia Médica 2025 |
| Generalistas sem título (2024) | 244,1 mil | Demografia Médica 2025 |
| Equipes de Saúde da Família cofinanciadas (2025) | 54,7 mil | Ministério da Saúde |
| Municípios usando o e‑SUS PEC (nov/2024) | 4.173 | Nota Técnica 22/2024 |
| UBS com prontuário eletrônico | 97,6% | Censo das UBS 2025 |
| Mercado global de IA para documentação | US$ 1–2 bi, 18–25% a.a. | Credence, Fortune BI, Grand View |

Não encontrado: tamanho do mercado brasileiro de IA para documentação, número de clínicas privadas, consultas anuais na atenção primária.

**Concorrentes.**

| Empresa | Modelo | Preço | Sinal |
|---|---|---|---|
| Voa Health | B2C freemium | Grátis 10/mês; Pro R$ 349/mês | 60,7 mil médicos declarados, cerca de 2 mil pagantes |
| Noa Notes (Doctoralia) | B2C e clínicas | Não publicado | Mais de 9 mil médicos declarados |
| Amplimed (Amélia) | IA nativa no prontuário | Complemento, não publicado | Concorre com o nosso adaptador Amplimed |
| iClinic (Afya) | Prontuário | R$ 89–299 por profissional/mês | Referência de tíquete |
| OM30 | B2G | Não publicado | Único concorrente voltado ao SUS encontrado |
| Freed, Heidi, Suki | B2C nos EUA | US$ 99–399/mês | Referência internacional |

Números de usuários são autodeclarados.

## 3. Custo unitário (estimativa)

- IA por consulta de 15 min: **R$ 0,11–0,21** (transcrição Whisper/Groq + SOAP com Claude Haiku; câmbio de R$ 5,50).
- Equipe de atenção primária com 400 consultas/mês: R$ 44–84.
- Médico de consultório com 250 consultas/mês: R$ 28–53.
- Fora da conta: hospedagem, suporte, implantação e impostos.

## 4. Os três modelos

| Critério | B2C | B2B | B2G |
|---|---|---|---|
| Quem paga | O médico | Clínica, fornecedor de prontuário, operadora | Secretaria municipal de saúde |
| Preço proposto | Grátis 5 consultas/mês; Pro R$ 119/mês (R$ 99 no anual) | R$ 99 por profissional/mês (mínimo 5) ou R$ 0,45 por consulta | R$ 150 por equipe/mês, com implantação |
| Ciclo de venda | Dias | 2 a 6 meses | 6 a 18 meses |
| Concorrência | Alta, com planos grátis | IA nativa nos prontuários | Um rival identificado |
| Margem bruta | 27–61% (já com o custo dos gratuitos) | 53–78% | 44–71% |
| Risco principal | Disposição a pagar de R$ 111/mês (MV 2026, n=112) | Parceiro internaliza a função | Ciclo longo e exigência de validação |
| Papel no plano | Motor de evidência | Canal oportunista | Tese principal |

**Como o município compra.** Dispensa de licitação até R$ 65.492,11 por ano (Decreto 12.807/2025), o que cobre até 36 equipes a R$ 150. Acima disso, CPSI (LC 182/2021): até R$ 1,6 milhão, 12 meses prorrogáveis por mais 12. Fontes de verba: Programa SUS Digital (Portaria 3.233/2024) e componente de qualidade do cofinanciamento da atenção primária (Portaria 3.493/2024). Conferir o enquadramento com o jurídico de cada município.

**Mercado potencial do B2G.** 54,7 mil equipes × R$ 150 × 12 = cerca de R$ 98 milhões por ano.

## 5. Projeção, cenário‑base (estimativa, não previsão)

Receita anual recorrente ao fim de cada ano.

| Linha | 2027 | 2028 | 2029 |
|---|---|---|---|
| B2G: equipes | 60 | 400 | 1.500 |
| B2G: receita | R$ 108 mil | R$ 720 mil | R$ 2,70 mi |
| B2C: assinantes Pro | 100 | 400 | 1.000 |
| B2C: receita | R$ 143 mil | R$ 571 mil | R$ 1,43 mi |
| B2B: consultas/mês | 0 | 30 mil | 150 mil |
| B2B: receita | 0 | R$ 162 mil | R$ 810 mil |
| **Total** | **R$ 251 mil** | **R$ 1,45 mi** | **R$ 4,94 mi** |

As 1.500 equipes de 2029 equivalem a 2,7% das equipes de Saúde da Família.

## 6. Riscos regulatórios

- **CFM 2.454/2026:** o médico responde pelo registro; o paciente é informado e pode recusar. Faltam a tela de consentimento (B28) e evidência de validação.
- **ANVISA RDC 657/2022:** transcrição e SOAP tendem a ficar fora; a sugestão de CID‑10 se aproxima de apoio à decisão. Interpretação do PO, sem posição oficial: pedir parecer.
- **LGPD:** dado de saúde é sensível. Faltam o relatório de impacto (RIPD) e contrato de IA sem uso dos dados para treino.
- **Compra pública:** os limites mudam por decreto; conferir na data.

Nenhum destes pontos impede o piloto com consultas simuladas. Todos precisam estar resolvidos antes do uso com paciente real.

## 7. Roteiro 2027

| Período | Etapa | Entregas |
|---|---|---|
| Jan–mar | Preparar | Consentimento, RIPD, parecer sobre a ANVISA, servidor hospedado |
| Abr–jun | Pilotar | Convênio UPE com 1 ou 2 municípios que usam o PEC, 10 a 20 equipes; medir tempo e qualidade do registro |
| Jul–set | Vender | Publicar o resultado; primeiro contrato por dispensa ou CPSI; abrir o plano Pro |
| Out–dez | Repetir | 3 municípios pagantes, 60 equipes; primeira conversa de marca branca |

Até o primeiro contrato o custo segue perto de zero (`docs/12`, custeio só em plataformas gratuitas).

## 8. Fontes

- Demografia Médica no Brasil 2025 (FMUSP, AMB, Ministério da Saúde).
- Ministério da Saúde: cartilha de 2025 sobre a atenção primária; Nota Técnica 22/2024; Censo das UBS 2025.
- Credence Research, Fortune Business Insights, Grand View Research (2025).
- JAMA Network Open 2025; NEJM AI 2025 (UCLA); Afya 2022.
- voa.health/precos; Startups.com.br; noa.ai; amplimed.com.br; Exame (OM30); Sacra; MobiHealthNews.
- Portarias GM/MS 3.493/2024 e 3.233/2024; LC 182/2021; Decreto 12.807/2025.
- Resolução CFM 2.454/2026; ANVISA RDC 657/2022.
- Pesquisa MV 2026 (n=112, sem representatividade estatística).
- groq.com/pricing e preços públicos da Anthropic.

— Dr. Rui Pontes, Product Owner
