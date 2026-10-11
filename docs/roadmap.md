# Próximas etapas

Atualizado em 9 de outubro de 2026. Itens pendentes são planejamento; não descrevem cobertura já disponível. A cobertura e suas datas estão em [Dados e SQLite](data.md).

## Rumo

O Painel Público é para o cidadão comum: abrir, entender em poucos segundos e saber quem o representa, quanto custa e como trabalha. A referência é o [TheyWorkForYou](https://www.theyworkforyou.com/), do Reino Unido: uma porta de entrada simples, votos explicados em linguagem clara e um jeito fácil de falar com o representante.

Antes de entrar no roadmap, cada item passa por duas perguntas:

1. Responde a uma pergunta que um cidadão comum faria sobre alguém que ele elegeu ou pode deixar de eleger?
2. Vale o custo de manter? As coletas são manuais, então cada fonte nova é trabalho permanente.

## Entregue

- Projeto organizado com Git, SQLite e design system, preservando a home e as telas.
- Consulta dos 513 deputados e dos 82 registros do Senado, com cobertura explícita e distinção entre ausência e zero.
- Fichas em "3 respostas" (custo, presença/Placar e maior alerta), com detalhes recolhidos, atividade e autoria do Senado e situação atual dos projetos (Etapas 1 a 3, integradas à `main`).
- Foco no cidadão (7/10/2026): saíram a busca avançada e os dados de servidores (SIAPE) e do Judiciário (DadosJusBr). O banco caiu de 1,27 GB para 84 MB sem mudar nenhuma resposta das telas, e cada ficha passou a oferecer o download de todas as notas da cota em CSV.
- **Eleições de 2026 e preparação para a troca de mandatos (7/10):** lista oficial separada do cadastro (`roster`), preservação das notas e alertas de quem sai e manutenção da lista anterior quando a coleta falha. Resultado do TSE na ficha quando há uma única candidatura correspondente; 551 dos 595 registros ligados na fotografia de 7/10. Implementação integrada à `main`; as próximas atualizações estão nas datas abaixo.
- **Minha cidade, versão 1 (7/10):** busca nacional, população do IBGE, representantes eleitos no TSE, votos municipais de deputados federais e links às fichas; emendas por município, autoria e ano, com empenhado, pago e restos a pagar separados; contas anuais municipais de 2025 e medianas por faixa populacional. As três fases estão implementadas e integradas à `main`. Cobertura, lacunas e recortes em [Dados e SQLite](data.md). Bens, financiamento de campanha e contas estaduais ficam como ampliações futuras.
- **Quanto custa um mandato (8–9/10):** custo médio mensal desde fev/2023, com partes, meses, fontes e lacunas explícitos, integrado à `main` nas fichas, lista e comparação. Na Câmara, salário bruto, auxílios, cota e verba de gabinete; no Senado, remuneração, equipe comissionada do gabinete e cota. Comparações e ordenações de custo são feitas dentro da mesma Casa, pois as fontes não publicam as mesmas partes. Valores da época, sem correção pela inflação. [Fontes](mandate-cost-sources.md), [coleta e regras](mandate-cost-collection.md), [verificações](mandate-cost-preflight.md) e [cobertura do mandato](data.md#quanto-custa-um-mandato--período-do-mandato-20232025-partes-baratas).
- **Complementos do mandato (8–9/10):** notas e CSV da cota desde fev/2023 nas duas Casas; alertas com base de 12 meses completos, concentração por ano e filtro por ano; presença da Câmara no mandato; votos nominais, autoria, presença pelo Diário, participação nas votações e licenças do Senado desde fev/2023. Presença pelo Diário cobre 296 de 301 sessões na primeira coleta, sem inferir faltas das sessões sem lista validada. Alertas do mandato já publicados; regras em [Alertas](alerts.md), demais fontes e limitações em [Dados e SQLite](data.md).

As entregas acima registram a implementação integrada à `main`. Publicação de código, banco e snapshots são etapas separadas; integrar o código não confirma que a base mais recente está no servidor. Procedimento em [Publicação](deploy.md).

## Agora, nesta ordem

1. **Placar mais amplo.** Em desenvolvimento na branch `codex/broader-voting-scoreboard`: inventário de 2026 com 159 candidatos revisados, 20 decisões nominais no catálogo local e 139 exclusões documentadas. Todas as 20 decisões têm link confirmado ao texto votado. Há resumos da versão votada, temas oficiais, busca, paginação e votos individuais carregados ao abrir a decisão, inclusive uma lista recuperada do relatório oficial após retorno vazio da API. [Metodologia e cobertura](voting-scoreboard.md). Continuam pendentes a conferência de possíveis omissões da fonte, a cobertura desde fevereiro de 2023, a integração à `main` e a publicação. Home, fichas e comparações mantêm as quatro seleções originais.
2. **Antes de divulgar o site:**
   - Atualização automática das cotas da Câmara e do Senado, com data da coleta, validação e registro das falhas. **Feito em 11/10/2026** (`ingest/pipeline.py` e `deploy/painel-ingest.timer`, ver [Publicação](deploy.md#atualização-automática-dos-dados)); falta ativar no servidor. Próximos passos da automação, nesta ordem: projetos pelos arquivos anuais da Câmara (sem recoleta por deputado); tirar as datas fixas dos coletores (meses `1-9`, `CURRENT_LAST_MONTH`, `LAST_PUBLISHED`, `ano=2026`); job mensal do custo do mandato e do Senado; fila editorial do Placar; eventos com data (segundo turno, nova legislatura).
   - Backup externo com teste de restauração. O backup local consistente já existe.
   - Confirmar o deploy pelo GitHub Actions no servidor e a publicação das bases e snapshots mais recentes.

## Atualizações com data marcada

- **Depois de 25/10/2026:** coletar novamente os resultados do TSE após o segundo turno, tanto para as fichas parlamentares quanto para Minha cidade. O bloco eleitoral só volta à home com cobertura ampla.
- **Em 1º/2/2027:** atualizar a lista oficial da nova legislatura, preservando os dados de quem sai; iniciar o novo recorte das médias e manter o mandato 2023–2027 como histórico nas fichas.

## Depois

- Ampliações de Minha cidade: bens declarados e financiamento de campanha do TSE; contas estaduais do SICONFI; fontes abertas de portais estaduais e Tribunais de Contas. Priorizar lugares mais populosos e fontes com arquivo ou API; raspar site vem por último. Onde não houver dado aberto, indicar a limitação. Comparações entre cidades e estados usam só a base nacional. Contas municipais mantêm o último ano fechado como régua.
- Apurar faltas e justificativas do Senado que não estejam cobertas pelos registros de participação nas votações e licenças. A presença pelo Diário já foi entregue; ausência nessa lista não é tratada como falta.
- Botão de destaque "Fale com ele(a)" na ficha, com o e-mail e o telefone do gabinete que já são coletados.
- Aviso por e-mail quando algo muda na ficha de quem a pessoa acompanha; depende da atualização automática.
- Busca por CEP em Minha cidade.
- Histórico anterior ao mandato atual (antes de 2023), somente com fonte validada e se houver demanda.
- Correção dos valores pelo IPCA, se houver demanda; hoje são mostrados os valores da época.

## Fora do escopo

Decidido em 7/10/2026, para manter o app simples:

- Remuneração de servidores, inclusive Ministério Público, tribunais de contas, militares, Banco Central e servidores do Legislativo.
- Aposentados e pensionistas.
- Busca avançada e ferramentas de pesquisa (filtros, anotações, acompanhamento no navegador). Quem precisa do dado bruto baixa o CSV da ficha.
- Contratos e licitações do PNCP como recurso próprio. Se voltarem, entram como um bloco de "Minha cidade" (maiores compras da prefeitura), nunca ligados a uma pessoa.

## Princípios

Toda ampliação mostra dados ausentes como ausência, nunca como zero. Sinais de atenção não são conclusões de irregularidade. Cada número indica fonte, período e onde conferir.
