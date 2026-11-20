# Anexo E — Apresentação do modelo econômico (texto dos slides)

*Texto dos 15 slides, na ordem. Os arquivos-fonte (HTML e CSS) estão em `E-apresentacao-modelo-economico/`. Apresentação: <https://claude.ai/artifact/P7uEbmXFH7sq3iyJ7qHy1P> (privada; peça acesso ao PO).*

## Slide 1

COPILOT MÉDICO · DA CONVERSA AO PRONTUÁRIO

**Modelo econômico**

B2C, B2B e B2G comparados com dados de mercado de 2024 a 2026, e o modelo recomendado para os próximos 36 meses.

Dr. Rui Pontes, Product Owner · novembro de 2026 · estimativas estão marcadas como tal


> Notas do apresentador: Abertura. O deck compara os três modelos e recomenda um. Todo número tem fonte no último slide; o que é cálculo nosso está marcado como estimativa.

## Slide 2

A RECOMENDAÇÃO, LOGO DE INÍCIO

Vender primeiro para a atenção primária do SUS.

O médico individual entra como prova de uso, e os fornecedores de prontuário como canal oportunista. O SUS é o único dos três mercados em que o CoPilot tem um diferencial difícil de copiar: escreve no e‑SUS PEC, usado em 4.173 municípios.


> Notas do apresentador: Modelo recomendado: híbrido com B2G como tese principal. B2C freemium enxuto gera evidência e marca. B2B só por parceria com quem não tem IA própria.

## Slide 3

ESTUDO DE MERCADO · A DOR

**O prontuário consome o médico, mas o ganho real da IA é modesto**

2 h

de prontuário para cada 1 h de atendimento, em estudos dos EUA.

62%

dos médicos brasileiros já tiveram burnout; 27% se dizem exauridos pela burocracia (Afya, 2022).

8–10%

é a redução medida de tempo de documentação com IA em estudos de 2025, não os 40% da propaganda.

Consequência comercial: prometer o que a evidência sustenta e medir o ganho no próprio piloto. Não há dado brasileiro de minutos de prontuário por consulta.

Fontes: JAMA Network Open 2025; NEJM AI (UCLA) 2025; Afya 2022. Detalhes no último slide.


> Notas do apresentador: A dor é real, mas os ensaios clínicos mostram ganho de 8 a 10% no tempo. Quem vender 40% vai decepcionar gestor público. Nosso piloto precisa produzir o número brasileiro.

## Slide 4

ESTUDO DE MERCADO · TAMANHO

**O mercado em seis números**

635,7 mil

médicos no Brasil, projeção para 2025.

244,1 mil

generalistas sem título de especialista, em 2024.

US$ 1–2 bi

mercado global de IA para documentação, crescendo 18–25% ao ano.

54,7 mil

equipes de Saúde da Família cofinanciadas em 2025.

4.173

municípios usando o e‑SUS PEC, em novembro de 2024.

97,6%

das UBS já usam prontuário eletrônico; 94,6% têm internet.

Fontes: Demografia Médica 2025; Ministério da Saúde (cartilha 2025, Nota Técnica 22/2024, Censo UBS); Credence, Fortune BI e Grand View. Não achei tamanho do mercado brasileiro de IA para documentação.


> Notas do apresentador: Linha de cima: mercado privado e global. Linha de baixo, em verde: a base instalada do SUS, que é onde o adaptador e-SUS PEC nos diferencia.

## Slide 5

| Empresa | Modelo | Preço | Sinal |
|---|---|---|---|
| Voa Health | B2C freemium | Grátis 10/mês; Pro R$ 349/mês | 60,7 mil médicos declarados, cerca de 2 mil pagantes |
| Noa Notes (Doctoralia) | B2C e clínicas | Não publicado | Mais de 9 mil médicos declarados |
| Amplimed (Amélia) | IA nativa | Complemento, não publicado | Concorre com o nosso adaptador Amplimed |
| iClinic (Afya) | Prontuário | R$ 89–299 por profissional/mês | Referência de tíquete de software de clínica |
| OM30 | B2G | Não publicado | Único concorrente voltado ao SUS que encontrei |
| Freed, Heidi, Suki | B2C nos EUA | US$ 99–399/mês | Abridge vale US$ 5,3 bi; capital abundante lá fora |
ESTUDO DE MERCADO · CONCORRENTES

**O privado está lotado; no SUS achei um rival**

Fontes: voa.health/precos e Startups.com.br (2026); noa.ai; amplimed.com.br; Exame (OM30); Sacra e MobiHealthNews. Números de usuários são autodeclarados.


> Notas do apresentador: A Voa tem cerca de 3% de pagantes sobre a base declarada (estimativa nossa). A Amplimed já embute IA: nosso adaptador Amplimed vira conflito, não diferencial.

## Slide 6

| Critério | B2C | B2B | B2G |
|---|---|---|---|
| Quem paga | O médico | Clínica, software, operadora | Secretaria municipal |
| Preço proposto | R$ 119/mês | R$ 99/mês ou R$ 0,45/consulta | R$ 150 por equipe/mês |
| Ciclo de venda | Dias | 2 a 6 meses | 6 a 18 meses |
| Concorrência | Alta, com planos grátis | IA nativa nos prontuários | Um rival identificado |
| Margem bruta | 27–61%, com o grátis | 53–78% | 44–71% |
| Risco principal | Médico aceita pagar R$ 111 | Conflito com a Amélia | Ciclo longo e validação |
| Papel no plano | Motor de evidência | Canal oportunista | Tese principal |
OS TRÊS MODELOS

**B2C, B2B e B2G lado a lado**

Preços, ciclos e margens são propostas e estimativas minhas, a partir do custo de IA por consulta (slide de custo unitário) e dos preços de mercado.


> Notas do apresentador: Leitura da tabela: B2C fecha rápido mas a margem some com o plano gratuito. B2B tem a melhor margem, mas depende de parceiro. B2G demora, porém é onde há menos concorrência e mais diferencial.

## Slide 7

MODELO 1 · B2C

**Médico individual: assinatura freemium**

- **Oferta**

Grátis: 5 consultas por mês.

Pro: R$ 119/mês, ou R$ 99 no plano anual, sem limite.

Canal: Chrome Web Store, indicação entre colegas, residências.

- **Economia**

Custo de IA: R$ 28–53 por médico pagante/mês (250 consultas).

Cada pagante sustenta cerca de 32 gratuitos: mais R$ 18–34.

Margem bruta: 27–61%.

- **Risco**

Disposição média a pagar: R$ 111/mês (MV 2026, n=112).

Voa e Noa já ocupam o espaço, com capital.

Conversão de grátis para pago perto de 3%.

Veredito: não sustenta a empresa sozinho. Vale como motor de evidência, de marca e de dados de uso para vender ao gestor.


> Notas do apresentador: O preço de R$ 119 fica logo acima da disposição a pagar medida e bem abaixo dos R$ 349 da Voa. O limite gratuito de 5 consultas, e não 10, é o que mantém a margem positiva. Margens e conversão são estimativas.

## Slide 8

MODELO 2 · B2B

**Clínicas, prontuários e operadoras**

- **Oferta**

Clínicas: R$ 99 por profissional/mês, mínimo de 5.

Prontuários sem IA própria: marca branca a R$ 0,45 por consulta.

Operadoras: por consulta, com relatório de qualidade do registro.

- **Economia**

Custo de IA: R$ 0,11–0,21 por consulta.

Margem bruta: 53–78%.

O parceiro traz a base de usuários; o custo de aquisição cai.

- **Risco**

A Amplimed já tem a Amélia; o iClinic é da Afya.

Dependência de um parceiro que pode internalizar a função.

Hospitais exigem integração e comitê de IA (CFM 2.454/2026).

Veredito: boa margem, pouca defesa. Só entrar por parceria com fornecedor de prontuário que ainda não tem IA.


> Notas do apresentador: O adaptador Amplimed foi construído no projeto, mas a Amplimed lançou IA própria. O B2B que sobra é marca branca para prontuários menores e contratos com operadoras. Preços e margens são propostas e estimativas.

## Slide 9

MODELO 3 · B2G

**Atenção primária do SUS, por equipe**

- **Oferta**

R$ 150 por equipe de Saúde da Família/mês, com implantação e treinamento.

Escreve o SOAP e o CID‑10 direto no e‑SUS PEC, após aprovação do médico.

- **Como o município compra**

Dispensa: até R$ 65.492,11 por ano, o que cobre até 36 equipes.

CPSI (LC 182/2021): até R$ 1,6 milhão, 12 meses mais 12.

Verba: SUS Digital e componente de qualidade do cofinanciamento.

- **Risco**

Ciclo de 6 a 18 meses, com calendário eleitoral e orçamentário.

Gestor exige validação; a sugestão de CID pode cair na ANVISA.

Internet e microfone nas UBS variam.

Veredito: tese principal. Mercado potencial estimado em R$ 98 milhões por ano (54,7 mil equipes a R$ 150).


> Notas do apresentador: O argumento para o gestor: registro melhor aumenta o repasse do componente de qualidade (Portaria 3.493/2024). O número de 36 equipes vem de 65.492 dividido por 1.800 reais por equipe ao ano; conferir o enquadramento com o jurídico do município.

## Slide 10

CUSTO UNITÁRIO

**A IA custa centavos por consulta**

R$ 0,11–0,21

por consulta de 15 minutos: transcrição (Whisper na Groq) mais SOAP (Claude Haiku).

44–71%

de margem bruta a R$ 150 por equipe, com 400 consultas por mês (R$ 44–84 de IA).

Fora desta conta: hospedagem, suporte, implantação e impostos. Usar o modelo de transcrição mais barato é o que segura a margem no SUS.

Estimativa minha com preços públicos de API e câmbio de R$ 5,50. Fontes: groq.com/pricing; preços da Anthropic via agregador.


> Notas do apresentador: Conta: 15 minutos de áudio custam de 1 a 3 centavos de dólar; o SOAP, cerca de 1 centavo. Total de 2 a 4 centavos de dólar. O piso da faixa usa o Whisper turbo.

## Slide 11

MODELO RECOMENDADO

**Híbrido, com o SUS no centro**

1 · PROVA

- **Piloto acadêmico**

Convênio UPE com 1 ou 2 municípios que usam o PEC, 10 a 20 equipes.

Sem custo para o município; mede tempo e qualidade do registro.

2 · RECEITA

- **Contrato municipal**

R$ 150 por equipe/mês, por dispensa ou CPSI.

O resultado do piloto é o argumento de venda e a validação que a CFM pede.

3 · ALAVANCA

- **B2C e marca branca**

Plano Pro a R$ 119 para o médico que conheceu o produto na UBS.

Marca branca para prontuários sem IA, quando houver evidência publicada.

Por que este: é o único dos três em que o diferencial (e‑SUS PEC, anonimização local, origem universitária) vale mais que capital de marketing.


> Notas do apresentador: A origem acadêmica é vantagem no B2G: convênio com universidade pública reduz a barreira de entrada e gera publicação. No B2C ela não vale nada contra uma startup com 3 milhões de dólares.

## Slide 12

| Linha | 2027 | 2028 | 2029 |
|---|---|---|---|
| B2G: equipes contratadas | 60 equipes | 400 equipes | 1.500 equipes |
| B2G: receita | R$ 108 mil | R$ 720 mil | R$ 2,70 milhões |
| B2C: assinantes Pro | 100 | 400 | 1.000 |
| B2C: receita | R$ 143 mil | R$ 571 mil | R$ 1,43 milhão |
| B2B: consultas por mês | Nenhuma | 30 mil | 150 mil |
| B2B: receita | Nenhuma | R$ 162 mil | R$ 810 mil |
| Total | R$ 251 mil | R$ 1,45 milhão | R$ 4,94 milhões |
PROJEÇÃO · CENÁRIO‑BASE

**Receita anual recorrente ao fim de cada ano**

Estimativa minha, não previsão: volumes são premissas. As 1.500 equipes de 2029 equivalem a 2,7% das 54,7 mil equipes de Saúde da Família.


> Notas do apresentador: Preços usados: R$ 150 por equipe/mês, R$ 119 por médico/mês e R$ 0,45 por consulta. O B2C parece maior em 2027 porque o primeiro contrato público só entra no segundo semestre. Tudo depende de o piloto acontecer no primeiro semestre de 2027.

## Slide 13

RISCOS REGULATÓRIOS

**Quatro portas antes do primeiro paciente real**

- **CFM 2.454/2026**

Médico responde pelo registro; paciente é informado e pode recusar.

Falta: tela de consentimento e evidência de validação.

- **ANVISA RDC 657**

Transcrição e SOAP tendem a ficar fora.

A sugestão de CID‑10 se aproxima de apoio à decisão: pedir parecer.

- **LGPD**

Dado de saúde é sensível.

Falta: relatório de impacto e contrato de IA sem uso dos dados para treino.

- **Compra pública**

Limites de dispensa e do CPSI mudam por decreto.

Conferir o enquadramento com o jurídico de cada município.

A leitura sobre a ANVISA é interpretação minha; não há posição oficial sobre IA de documentação. Fontes: CFM; ANVISA, perguntas e respostas da RDC 657; Decreto 12.807/2025.


> Notas do apresentador: Nenhum destes pontos impede o piloto com consultas simuladas. Todos precisam estar resolvidos antes do uso com paciente real e antes do primeiro contrato pago.

## Slide 14

ROTEIRO · 2027

**Do piloto ao primeiro contrato em 12 meses**

JAN–MAR

- **Preparar**

Tela de consentimento, relatório de impacto, parecer sobre a ANVISA.

Servidor hospedado, sem Docker na UBS.

ABR–JUN

- **Pilotar**

Convênio UPE com 1 ou 2 municípios, 10 a 20 equipes.

Medir tempo de registro e qualidade do SOAP.

JUL–SET

- **Vender**

Publicar o resultado do piloto.

Primeiro contrato por dispensa ou CPSI; abrir o plano Pro.

OUT–DEZ

- **Repetir**

3 municípios pagantes e 60 equipes.

Primeira conversa de marca branca com um prontuário.

Decisão pedida agora: aprovar o B2G como tese principal e buscar o município do piloto ainda em 2026.


> Notas do apresentador: Até o primeiro contrato o custo segue perto de zero: camadas gratuitas, convênio acadêmico e a equipe do ciclo 6. O que custa dinheiro, hospedagem e IA em volume, só começa com receita contratada.

## Slide 15

FONTES E PREMISSAS

**De onde vêm os números**

- Médicos: Demografia Médica no Brasil 2025 (FMUSP, AMB, Ministério da Saúde).

- Atenção primária: cartilha do Ministério da Saúde 2025; Nota Técnica 22/2024 (PEC em 4.173 municípios); Censo das UBS 2025.

- Mercado global: Credence Research, Fortune Business Insights, Grand View Research (2025).

- Evidência clínica: JAMA Network Open 2025; NEJM AI 2025 (UCLA); Afya 2022.

- Concorrentes: voa.health/precos; Startups.com.br; noa.ai; amplimed.com.br; Exame (OM30); Sacra; MobiHealthNews.

- Compra pública: Portarias GM/MS 3.493/2024 e 3.233/2024; LC 182/2021; Decreto 12.807/2025.

- Regulação: Resolução CFM 2.454/2026; ANVISA RDC 657/2022.

- Disposição a pagar: pesquisa MV 2026 (n=112, sem representatividade estatística).

- Custos de IA: groq.com/pricing e preços públicos da Anthropic, câmbio de R$ 5,50.

Não encontrei: número de clínicas privadas, consultas anuais na atenção primária, preço da Noa e da Amélia, ciclo real de venda a municípios. Preços, margens e projeção são propostas e estimativas minhas.


> Notas do apresentador: Números de usuários dos concorrentes são autodeclarados. Antes de usar o deck com investidor ou gestor, conferir os limites de dispensa e o status da regulamentação na data.

