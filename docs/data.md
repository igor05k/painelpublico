# Dados e SQLite

O banco local fica em `data/na-lupa.sqlite3` (nome preservado para não duplicar a base existente). Não é enviado ao navegador e não entra no Git. Toda a pasta `data/`, inclusive os snapshots complementares, permanece local; o repositório público contém apenas código, testes e documentação. Configure outro caminho por `PAINEL_DB` ou por `--db` nos comandos Python. Caminhos relativos de `PAINEL_DB` partem da raiz do projeto.

```sh
make db-backup   # cópia consistente em data/backups/, sem sobrescrever
make db-init     # cria/atualiza esquema, sem baixar ou importar registros
make db-check    # integridade, chaves estrangeiras, versão e contagens
make import     # data/imports/ → SQLite, preservando rollback em caso de falha
```

O esquema está em `backend/schema.sql`; `backend/database.py` controla a versão com `PRAGMA user_version`. A primeira migração adota o banco existente sem apagar registros. Mudanças futuras devem incluir migração e teste antes de subir a versão. A conexão habilita chaves estrangeiras; não há troca automática de journal mode nesta organização.

Backup usa a API do SQLite, podendo operar com o app aberto. Para restaurar: pare o servidor, guarde uma cópia do banco atual e aponte `PAINEL_DB` para o backup validado. Não substitua arquivos de banco enquanto o servidor estiver usando-os. Backups locais ainda precisam de uma política externa antes de produção.

## Coletas manuais

```sh
python3 ingest/legislative.py --year 2026
make db-backup
make import
make db-check
```

No servidor, essa sequência roda sozinha todo dia para o ano corrente, com backup, cópia de trabalho, guarda de regressão e aviso por e-mail: `python3 -m ingest.pipeline daily` (`make update-daily`), descrito em [Publicação](deploy.md#atualização-automática-dos-dados). Os demais coletores desta página continuam manuais.

Os importadores atuais usam apenas a biblioteca padrão do Python. Downloads podem ser grandes. Os snapshots normalizados ficam em `data/imports/`, e os originais/cache em `data/raw/`. Nem todos os brutos são retidos; preserve os normalizados se precisar reconstruir exatamente a mesma fotografia. Recoletar uma fonte pode produzir outro retrato.

Complementos manuais da Câmara:

```sh
python3 ingest/editorial/collect.py deputies
python3 ingest/editorial/collect.py presence 150
python3 ingest/editorial/collect.py build
python3 ingest/editorial/collect.py votes
make build
```

`deputies` segue todos os links de paginação da API oficial e grava um cache completo separado do cache antigo. `presence SECONDS` consulta os perfis dentro do tempo informado; pode ser repetido para preencher o cache local. `build` processa somente páginas de presença disponíveis e grava `presenca-2026.json` (só o ano corrente); a presença que as telas usam, `presenca.json`, cobre o mandato e vem de `make collect-mandate-history` (ver abaixo). Perfil sem resposta continua ausente, sem virar zero. `votes` lê os IDs selecionados e versionados em `frontend/data/votes.json` e coleta todas as linhas de participação de cada votação. As respostas oficiais ficam em `data/raw/editorial-extra/`; os snapshots resultantes são opcionais. Esses comandos só rodam quando chamados: `make dev`, `make build` e o uso do app não iniciam coleta nem atualização automática.

As fichas federais têm um coletor complementar manual, sem dependências externas:

```sh
make collect-profiles                 # completa caches ausentes das fichas
python3 ingest/profiles.py --collect --refresh  # atualiza os caches oficiais
python3 ingest/profiles.py            # reconstrói o snapshot sem rede
make build
```

`ingest/profiles.py` usa os IDs das listas oficiais em `data/imports/legislative.json` — 595 registros nesta fotografia — e escreve
`data/snapshots/perfis.json`. O cache em `data/raw/profiles/` contém somente campos selecionados de contato
institucional, mandato, projetos e gabinete; respostas de detalhe com CPF e outros dados pessoais não são
salvas integralmente. A coleta usa no máximo quatro consultas concorrentes. Falhas preservam a última
observação disponível e sua data, com indicação de falha; não produzem valor zero. `--limit N` permite
uma coleta curta de diagnóstico. Nenhum desses comandos agenda atualizações.

Os coletores de perfis continuam sendo a fonte manual dos complementos para a lista completa; contatos, projetos, gabinete e presença têm a cobertura registrada em seus snapshots. A arrecadação federal (`arrecadacao.json`) é outro complemento atualizado manualmente, com fonte e data: use as receitas administradas pela Receita Federal (impostos e contribuições), não o total das receitas federais, que inclui receitas de outros órgãos que não são tributos. A estadual (`state-tax-revenue.json`) vem de `python3 -m ingest.state_tax_revenue`: soma ICMS, IPVA e ITCD do Anexo 3 do RREO (Siconfi) dos 27 estados, do último bimestre em que todos entregaram, antes das transferências aos municípios e do Fundeb; estado sem relatório não vira zero, e o build só usa o arquivo com os 27. Impostos municipais ainda ficam de fora, porque cidades pequenas só detalham a receita mensal a cada semestre. Os geradores da página e dos PDFs da amostra editorial foram removidos. `ingest/editorial/requirements.txt` só é necessário para as ferramentas opcionais de passagens e agregação eleitoral; não é requisito do app nem do build.

## Placar — inventário e catálogo nominal

`make collect-vote-inventory YEAR=2026 THROUGH=2026-10-09` consulta a lista
completa do Plenário (órgão 180) e uma amostra limitada de detalhes e votos.
`python3 -m ingest.chamber_vote_inventory --year 2026 --through 2026-10-09`
reconstrói o relatório sem rede, usando os mesmos caches e limites.

Os originais, URLs, datas e checksums ficam em `data/raw/chamber-vote-inventory/`;
os relatórios JSON/Markdown, em `data/reviews/`. Tudo permanece fora do Git.
O inventário não publica candidatos automaticamente. Método nominal, objeto
votado, texto e ausência de votos exigem conferência; contagens e registros
individuais não comprovam sozinhos o método. Regra, limites e exemplos em
[Metodologia do Placar](voting-scoreboard.md).

Resultado em 9/10/2026: 1.339 registros retornados pela lista oficial em 14
páginas, 162 candidatos provisórios, 40 detalhes conferidos e 10 conjuntos de
votos individuais com os placares publicados reconciliados. Esses números
descrevem o levantamento inicial.

Na etapa seguinte, os 19 candidatos com placar explícito tiveram relatório
nominal e versão decidida conferidos, com todos os votos individuais conciliados.
O catálogo inicial tinha 19 decisões. A revisão dos 143 candidatos restantes e
dos 157 registros desconhecidos confirmou mais uma decisão nominal. A triagem
v2 tem 159 candidatos: 20 publicados, 139 excluídos com evidência e nenhum
pendente de método ou objeto. O catálogo local tem 8.240 registros individuais.
Os quatro links de texto inicialmente pendentes foram recuperados. O último,
do PL 4.133/2023, foi confirmado pelo vínculo oficial do SBT 1 ao anexo do parecer
e pela identificação do objeto nas notas da sessão. Não é cobertura completa
do ano nem do mandato. Campo não publicado,
inclusive abstenção ou tema, permanece ausente.

`make collect-votes THROUGH=2026-10-09` lê as revisões locais em
`data/reviews/chamber-vote-reviews-2026-10-09.json` (e, quando existir,
`data/reviews/chamber-vote-segment-reviews-2026-10-09.json`, com destaques e emendas da
mesma sessão; ver [Metodologia do Placar](voting-scoreboard.md)) e gera
`data/snapshots/chamber-votes.json` e `data/snapshots/chamber-vote-details/`.
`python3 -m ingest.chamber_votes --through 2026-10-09` reconstrói sem rede.
Revisões, fontes e snapshots ficam fora do Git; falhas preservam a saída anterior.
A triagem ampliada é reconstruída com `--detail-limit 400 --participant-limit 19 --audit-unknown`.
Uma revisão pode ser confirmada, pendente ou excluída com motivo e fonte.
No PL 1.625/2026, a API omite o placar e retorna votos individuais vazios: a
revisão explícita permite usar o relatório nominal, com 381 pessoas ligadas
sem ambiguidades a IDs da lista oficial da mesma data. As contagens disponíveis
da API são preservadas e comparadas com o relatório; ausência de linha não
vira zero. A origem complementar aparece em `dataNotes` na decisão.
A API pagina os resumos e carrega os votos individuais por decisão. A home,
fichas, partidos e comparações mantêm as quatro seleções originais. Um clone
sem catálogo mostra essas seleções com a limitação explícita.

## Base e recursos

O esquema normalizado contém `sources(id,label,url,scope,period,status,detail,fetchedAt)`,
`authorities(id,name,role,branch,sphere,institution,uf,party,sourceId,sourceUrl,position,employmentStatus,positionCount,positions,searchText)`,
`suppliers(key,name,cnpj)` e
`expenses(id,authorityId,sourceId,date,year,month,category,amountCents,documentId,documentUrl,supplierKey,kind,firstSeen,lastChanged)`;
`authority_totals`, `supplier_totals`, `signals` e `meta` guardam agregados, sinais e controle do retrato. Valores em
`amountCents` são centavos. A natureza separa reembolso de remuneração; os dois não são somados como um custo único.

`roster(sourceId,authorityId)` guarda quem está em cada lista oficial (deputados e senadores em exercício) na coleta completa
mais recente; o cadastro e o histórico ficam em `authorities`. Só uma lista coletada por inteiro substitui a anterior: quem sai
deixa de contar como em exercício e passa a aparecer como fora da lista atual, sem perder notas nem alertas. Uma coleta
indisponível mantém a lista anterior. A versão 2 do esquema cria a tabela a partir dos cadastros atuais; `make db-init` e o
próprio servidor, ao iniciar, aplicam a migração.

Na fotografia de 6 de outubro de 2026 (importada em 7/10), o banco tem 671 cadastros — 513 deputados e 82 registros do Senado
nas listas atuais, mais 76 registros que só aparecem nos arquivos de despesas (54 deputados, 10 do Senado e 12 contas
institucionais de lideranças) —,
127.778 notas de reembolso, 22.216 chaves de fornecedor e 3.572 sinais. Fornecedores são associados por CNPJ quando a fonte o publica; chaves alternativas
são limitadas à fonte e não garantem conciliação de empresas com nomes iguais.

A home, o resumo e a lista parlamentar consultam o roster atual da Câmara e do Senado no SQLite, junto com todos os reembolsos importados desses registros. As contagens cobrem a lista inteira; médias incluem somente parlamentares com reembolso observado e ausências continuam sem valor, nunca zero. A classificação mostra cinco nomes por espaço visual, mas considera todos os deputados com dados. Não há resultados eleitorais para a lista completa; o bloco eleitoral da home foi removido até haver cobertura ampla.

Cada ficha com notas importadas oferece o download de todas as notas da cota da pessoa em CSV (`/api/c/gastos.csv?id=<id>`,
separador `;`): competência, data de emissão, categoria, valor, fornecedor, CNPJ, documento e fonte. Células de texto que começam
com `=`, `+`, `-` ou `@` recebem um apóstrofo para não virarem fórmulas na planilha. Não há outra exportação nem busca avançada.

O radar aplica três cortes a reembolsos, com a regra, os prazos e a cobertura descritos em [Alertas](alerts.md):
lançamento de pelo menos R$ 10.000 (só nas notas detalhadas do ano corrente); concentração de pelo menos 50% do total anual
com um fornecedor na mesma fonte, com soma mínima de R$ 30.000, em cada ano do mandato; e mês pelo menos 1,75 vez a mediana
dos 12 meses anteriores completos (atravessando o ano, a partir de fev/2024), com diferença mínima de R$ 10.000 e valor acima
da mediana dos meses positivos de todos os parlamentares da mesma fonte e ano (piso pelos colegas, exigido a partir de cinco
meses observados). O piso evita que quem gasta pouco o ano todo vire alerta por um mês ainda abaixo do que os colegas gastam
normalmente. Meses seguidos acima do critério, no mesmo ano, contam como um único alerta, registrado no primeiro mês da
sequência. Só entram meses com o prazo de apresentação das notas encerrado. São critérios de triagem, não conclusões sobre conduta. Valores negativos são preservados e podem ser créditos ou estornos; documentos repetidos
exigem conferência na fonte. Referências idênticas não são deduplicadas como se fossem pagamentos repetidos.

Os alertas aparecem dos mais recentes aos mais antigos, com filtro por ano (`/api/c/radar?ano=AAAA`). Cada alerta da visão
cidadã traz uma linha de contexto com o total do ano na cota e a diferença para a média do cargo
(deputados ou senadores com notas importadas); diferenças menores que 10% aparecem como “parecido com a média”. A ordem
“Maior valor em alerta” soma os valores dos alertas `pico` e `fornecedor` de cada pessoa, em vez de contar alertas. O radar
da visão cidadã lista só deputados e senadores; contas institucionais (lideranças) continuam na base, mas não aparecem nas telas.

O app não grava nada no navegador: não há cadastro, anotações nem acompanhamento salvos localmente.

## Cobertura em 6 de outubro de 2026

- **Câmara:** lista oficial de 513 deputados; CEAP 2026 parcial, 113.065 linhas no arquivo consultado, com emissões de 1/12/2025
  a 5/10/2026. Inclui contas institucionais de lideranças; valores negativos mantêm o sinal da fonte.
- **Senado:** lista oficial de 82 senadores; CEAPS 2026 parcial, 14.713 linhas consultadas. A data do documento pode divergir da
  competência.
Remunerações de servidores federais (SIAPE), do Judiciário (DadosJusBr) e a composição do STF foram retiradas em 7/10/2026:
o painel cobre quem exerce mandato federal eleito. O banco anterior, com esses recortes, ficou guardado só localmente, em
`data/backups/na-lupa-antes-de-remover-servidores-20261007.sqlite3`. A cobertura eleitoral de estados e municípios está descrita na seção Minha cidade, abaixo.
Despesas estaduais e municipais continuam planejadas em [Próximas etapas](roadmap.md).

Fontes: [CEAP da Câmara](https://www.camara.leg.br/cotas/Ano-2026.csv.zip), [CEAPS do
Senado](https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/2026).

Referências documentais numéricas ambíguas com 11 dígitos (formato de CPF) são ocultadas; isso também pode ocultar um número de
documento legítimo nesse formato.

## Cobertura das telas de parlamentares

A consulta principal usa as listas oficiais importadas: 513 deputados e 82 registros de senadores nesta fotografia. Os 513 IDs da Câmara coincidem com as seis páginas coletadas da API. O total do Senado não é uma contagem de cadeiras: o XML inclui Lourdinha Pereira como segunda suplente, com exercício de 5/8/2026 a 6/10/2026 e motivo publicado de retorno do titular.

A reconciliação de 7/10/2026 reprocessa essa mesma fotografia do XML (`Metadados/Versao`: `06/10/2026 19:19:34`), sem nova coleta nem mudança de cobertura. O adaptador usa `Mandato/UfParlamentar` quando a identificação não informa UF; assim recupera MA para esse registro. Importa `Mandato/DescricaoParticipacao` em `position` e descreve em `employmentStatus` o exercício com a data de início mais recente, independentemente da ordem do XML. A ficha do Senado mostra participação, intervalo e motivo de término quando informados, com link da fonte. Datas ausentes, inválidas ou conflitantes não geram uma situação inferida; intervalo sem término informado não confirma exercício na data de hoje. Os 82 IDs da lista e as despesas históricas são preservados. Não se deduplicam suplentes e titulares como se fossem a mesma pessoa.

Há reembolsos associados a 509 dos deputados e 79 dos registros do Senado. Os demais devem aparecer como dados ausentes, não como zero. Outros 54 deputados e 10 registros do Senado têm notas em 2026 mas não estão nas listas atuais, como suplentes que deixaram o exercício: as fichas e os alertas deles continuam acessíveis, com o rótulo "fora da lista atual", e não entram em contagens, médias nem listas. A lista, o Placar e as comparações abrem a mesma ficha parlamentar. Os antigos detalhes e PDF de dez deputados e a análise editorial de despesas foram removidos.

`frontend/scripts/profile-data.js` concentra a leitura do snapshot complementar, presença e votos. Contatos e situação da Câmara vêm do detalhe oficial de cada deputado; verba e equipe de gabinete vêm da página oficial, com ano, meses publicados e data de atualização. Projetos da Câmara abrangem PL, PLP e PEC apresentados desde 1/2/2023: total só é confirmado quando todas as páginas da consulta são lidas. O resumo dessa API não fornece a situação atual; a coleta separada da Etapa 3, descrita abaixo, consulta os IDs já listados e preserva lacunas. Contatos e participação/exercício do Senado vêm do XML reconciliado. Autoria do Senado usa a API substituta `/dadosabertos/processo`, com o filtro `codigoParlamentarAutor` validado; a cobertura está detalhada abaixo. Gabinete do Senado ainda não tem fonte integrada.

Na coleta de 7/10/2026, o complemento contém os 595 IDs da lista: 513 deputados e 82 registros do Senado. Na Câmara, há e-mail para 513, telefone/endereço para 512, gasto de gabinete para 512 e equipe ativa para 512; dois perfis têm a seção de gabinete parcial. A consulta de projetos concluiu a paginação dos 513 perfis (quatro com zero resultados no recorte): são 35.746 associações entre autor e projeto, correspondentes a 19.878 IDs de proposição distintos, pois há coautorias. No Senado, o XML da fotografia de 6/10 informa e-mail para 78 e telefone para 80; 81 registros têm ao menos um desses contatos. Campos não publicados continuam sem valor. Essas contagens não ampliam o recorte de despesas no SQLite.

O salário nas fichas e comparações é o subsídio bruto de referência do cargo, com fonte oficial e vigência; não comprova pagamento individual. Folha, descontos e outras verbas parlamentares ainda não foram importados. Cota, verba de gabinete e subsídio não são somados. O build pode ser feito sem snapshots; complementos disponíveis identificam seu recorte e sua fonte.

A presença complementar cobre 512 dos 513 deputados; Gilmar Machado não tem dias extraídos no snapshot. Somente denominadores positivos e contagens consistentes entram nas porcentagens. Os votos embutidos na home cobrem as quatro seleções originais; fichas e comparações entre deputados(as) usam o catálogo do Placar (`/api/c/votes/person/camara:<id>`: voto da pessoa em cada votação, `null` quando a lista oficial não tem linha dela; `pairAgreement`: fração dos pares de deputados(as) com voto registrado na mesma votação que votaram igual, somada em todas as votações do catálogo, usada como referência "dois deputados quaisquer" na imagem da comparação); o catálogo nominal do Placar usa os snapshots separados descritos acima. A comparação de partidos usa o catálogo do Placar na Câmara (`/api/c/votes/party-totals`, totais por sigla publicada em cada votação) e as votações nominais coletadas no Senado. Linha ausente significa registro não importado, nunca a inferência de que a pessoa não votou; votação secreta informa somente participação. As comparações de concordância usam apenas votações com registro para ambos. Cadastro completo não significa histórico de presença, votações e remunerações completo.

### Atividade e autoria do Senado — mandato desde fevereiro de 2023

```sh
# Só a coleta de PDFs de presença requer esta dependência opcional:
python3 -m pip install -r ingest/senate-requirements.txt
make collect-senate-mandate THROUGH=2026-10-09
# Presença continua separada, em 2026:
python3 ingest/senate_attendance.py --collect --refresh --year 2026
python3 ingest/senate_projects.py --collect --refresh --mandate --through 2026-10-09
python3 ingest/senate_activity.py --collect --refresh --mandate --through 2026-10-09
# Reconstrução dos snapshots sem acessar a rede:
python3 ingest/senate_attendance.py --year 2026
python3 ingest/senate_projects.py --mandate --through 2026-10-09
python3 ingest/senate_activity.py --mandate --through 2026-10-09
make build
```

Os coletores são manuais. `--mandate` consulta fatias anuais desde 1/2/2023 até a data de corte; sem `--through`, usa a data da execução. `--year` mantém o modo anual para diagnóstico e escreve o mesmo destino: use `--output` no coletor de votos ou uma raiz isolada nos testes para não substituir o snapshot de mandato. `make collect-senate` preserva a coleta de presença de 2026 e chama a coleta de votos/autoria do mandato. Caches ficam em `data/raw/senado-projetos/` e
`data/raw/senado-atividade/` e `data/raw/senado-presenca/`; os snapshots correspondentes, em `data/snapshots/`.
Autoria é mesclada na resposta individual `/api/c/perfil/<id>`, preservando contato e
mandato. Votos e presença chegam por `/api/c/senado/atividade`, somente quando uma
ficha ou comparação precisa deles. O HTML leva apenas o marcador de disponibilidade.
Nenhum dado novo é embutido na home ou importado no SQLite.

**Autoria:** [API oficial de processos](https://legis.senado.leg.br/dadosabertos/v3/api-docs),
endpoint `/processo`, filtros `codigoParlamentarAutor`, `sigla=PL,PLP,PEC`,
datas anuais limitadas a 1/2/2023–9/10/2026. Na coleta local de 9/10, as 324 consultas
(81 senadores da lista atual × quatro anos) responderam com arrays válidos:
5.996 associações senador–projeto, 2.527 IDs distintos e dois perfis com total zero confirmado.
A seleção respeita o roster atual importado; não promete autoria de todos os ex-senadores do período.
Inclui coautorias,
portanto a soma por senador não é uma contagem de projetos distintos. Mantém somente
processos `objetivo=Iniciadora`: substitutivos posteriores podem herdar o autor do projeto
original e não são novos projetos de sua autoria. O serviço não documenta paginação
nem publica total independente; a cobertura se refere aos arrays retornados pelos
filtros oficiais, não a uma auditoria da completude interna da fonte. O serviço legado
anunciava descontinuação em 1/2/2026 e não é usado. Situação atual vem da coleta separada da Etapa 3, descrita abaixo, sem inferência a partir da autoria. As duas Casas agora começam em fevereiro de 2023. Cada item do Senado conserva a data de apresentação. IDs repetidos são contados uma vez por pessoa; o total só é confirmado se todas as fatias anuais forem importadas. `sources` e `yearlyCoverage` guardam fontes, datas pedidas/observadas e falhas por ano; a ficha e as comparações mostram esses períodos. Falha de atualização preserva os itens e a data anterior, com cobertura parcial.

**Votos:** [API oficial de votações](https://legis.senado.leg.br/dadosabertos/v3/api-docs),
consultas anuais de 1/2/2023 a 9/10/2026, respeitando o limite de um ano por chamada.
Foram importadas 183 votações públicas nominais, com 14.823 linhas individuais, e excluídas
240 secretas. A classificação exige `votacaoSecreta=N` e escolhas nominais explícitas;
cinco registros sem a expressão “Votação nominal” na descrição têm escolhas individuais
Sim/Não e foram incluídos após conferência. Uma lista só de presença não comprova votação nominal.
Nenhum ano ficou parcial na coleta local. As secretas ficam
fora dos itens e de todos os denominadores de escolha nominal. Registros sem escolha
(presença sem voto, atividade parlamentar, licenças, missão, não comparecimento e
presidência) são mantidos como registros, sem virar votos nem faltas. A comparação de
pessoas usa somente Sim, Não, Abstenção ou Obstrução presentes para os dois senadores;
casas diferentes não têm concordância calculada. O resumo da ficha informa em quantas
votações com linha individual foi identificado um voto; chamadas sem linha dessa pessoa
não entram no denominador, e registros sem voto não são classificados como faltas.
A lista completa deste recorte é distinta das quatro seleções originais das fichas da Câmara e do catálogo nominal separado do Placar.
Cada item aponta para a consulta oficial da sessão; os títulos vêm da descrição e da
identificação da matéria, sem resumo editorial novo. Falha de atualização preserva a
fotografia anterior e sua data, com status parcial.

Resultado da coleta local (9/10/2026), ainda sem publicação:

| Ano | Votações públicas nominais | Vínculos de autoria/coautoria | Projetos distintos |
| --- | ---: | ---: | ---: |
| 2023, desde fevereiro | 50 | 2.254 | 835 |
| 2024 | 58 | 1.501 | 595 |
| 2025 | 56 | 1.456 | 638 |
| 2026, até 9/10 | 19 | 785 | 459 |

`senado-atividade.json` e `senado-projetos.json` mantêm os nomes e contratos existentes,
com metadados de período adicionais. A presença incorporada em `senado-atividade.json`
permaneceu idêntica à fotografia anterior de 2026; nenhum PDF histórico foi coletado.
A situação dos 2.527 projetos distintos também foi consultada: 66 leis, duas emendas
constitucionais, 2.119 em tramitação e um arquivado/rejeitado segundo as regras existentes.
Outros 339 não confirmam um desses quatro grupos; a descrição oficial continua visível,
sem inferir aprovação ou rejeição. Caches da Câmara foram reaproveitados.

**Presença registrada:** a [agenda mensal oficial](https://legis.senado.leg.br/dadosabertos/plenario/agenda/mes/20260401)
é consultada desde o primeiro dia de cada mês; a API lista eventos da data informada
até o fim do mês. O coletor considera sessões deliberativas ordinárias/extraordinárias
realizadas e cruza o [calendário por data de sessão do DSF](https://legis.senado.leg.br/diarios/ver)
com os cadernos. Baixa somente o sumário e as páginas necessárias da tabela
“Registro de Comparecimento” (com ou sem “e Voto”), validando data, tipo de sessão e
total “Compareceram N senadores”. A evidência positiva é a marca na coluna Presença ou,
no formato que publica a coluna Horário, o registro nominal explícito de data e hora
do comparecimento. Marcas na coluna Voto não são usadas como presença. Cada tabela
guarda o método aplicado. Cadernos repetidos da mesma sessão são conciliados por data,
tipo e número da sessão. Texto selecionado e observações validadas
ficam no cache local, com URL e data; falhas de atualização preservam evidência anterior.
A extração de PDF é a única parte que requer a dependência opcional descrita acima;
modo offline, build, testes e servidor não precisam dela.

Na consulta de 7/10/2026 foram validadas **42 tabelas**, em um universo de 45 eventos
deliberativos realizados enumerados na agenda: 41 com marcas na coluna Presença e
uma, de 29/4, com 79 horários nominais e total oficial de 79 comparecimentos.
Há observações positivas associadas a 80 IDs do cadastro. Faltam tabelas validadas
para 1º e 2/9 (atas da sessão deliberativa contínua sem seção de comparecimento
identificada nos sumários) e 6/10 (sem caderno no calendário consultado).
Outras 215 linhas, de 21 nomes ou grafias extraídas, não coincidiram com um nome
normalizado único do cadastro atual. Há nomes históricos e erros de reconhecimento
de texto nos PDFs; essas linhas foram preservadas no cache, mas não atribuídas por
aproximação. Isso pode subcontar comparecimentos de pessoas com outros registros
válidos. As contagens exibidas são somente as observações positivas associadas,
não o total certificado de presença de cada senador em 2026.

O nome publicado é associado somente a um nome normalizado único no cadastro local.
Nomes sem correspondência ou ambíguos não recebem ID por aproximação. O snapshot
`senado-presenca.json` guarda as sessões, links dos Diários, IDs associados e contagens
positivas por pessoa; `senado-atividade.json` incorpora essa seção na reconstrução.
A legenda usada para agrupar essas presenças é a do cadastro atual, enquanto votos
usam a legenda publicada em cada votação. O denominador de dias, faltas e faltas
justificadas permanecem nulos. Perfis sem marca positiva permanecem sem dado, nunca
com zero inferido. As comparações mostram sessões com presença registrada e, nos
partidos, a média apenas entre pessoas com registros positivos, sem ranking de
assiduidade e sem comparar essa métrica com o percentual da Câmara.

O [tutorial oficial de assiduidade](https://www12.senado.leg.br/assessoria-de-imprensa/guia-para-jornalistas/tutorial-de-verificacao-da-assiduidade-dos-senadores)
explica que registrar presença isoladamente não confirma a assiduidade: é preciso
verificar votações e justificativas, publicadas separadamente. Por isso a integração
é **parcial para presença**: não exibe percentual, selo comparativo nem barra de
faltas do Senado. Apurar faltas e justificativas permanece pendente; não se deduz
nenhum desses estados a partir de uma omissão na tabela ou no arquivo de votos.

### Situação atual dos projetos — Etapa 3

`ingest/project_status.py` consulta somente os IDs de projetos que já existem nas
fichas locais: Câmara em `perfis.json`, Senado em `senado-projetos.json`. Coautorias
são deduplicadas para a coleta; cada ficha conserva sua própria lista e contagem.
Não há ampliação do período de autoria nem substituição do snapshot original.

```sh
make collect-project-status
# Atualização explícita de todas as consultas:
python3 ingest/project_status.py --collect --refresh
# Reconstrução sem rede, mantendo a data real das consultas em cache:
python3 ingest/project_status.py
make build
```

Os arquivos brutos e seus metadados (URL, data da consulta e SHA-256) ficam em
`data/raw/projetos-situacao/`. O snapshot `data/snapshots/projetos-situacao.json`
usa chaves `camara:<idProposicao>` e `senado:<idProcesso>`; IDs numéricos de casas
diferentes nunca são fundidos. A API `/api/c/perfil/<id>` anexa `situacaoAtual`
somente aos projetos daquela pessoa, sem embutir o conjunto no HTML e sem gravar
no SQLite. Para testar alterações da API, reinicie o servidor Python e recarregue
a página. Novas coletas podem ser relidas sem reiniciar: o cache acompanha o mtime.

**Câmara:** os [arquivos anuais oficiais de proposições](https://dadosabertos.camara.leg.br/swagger/api.html)
de 2023, 2024, 2025 e 2026 fornecem `ultimoStatus`, com descrição da situação, código
e data. Por exemplo: [arquivo de 2026](https://dadosabertos.camara.leg.br/arquivos/proposicoes/json/proposicoes-2026.json).
O coletor lê esses quatro arquivos, filtra os IDs já listados e só consulta
`/api/v2/proposicoes/<id>` para IDs não encontrados ou referências normativas.
O detalhe chama esse campo de `statusProposicao`. A consulta resumida em lote não
fornece situação. Situações vazias aparecem também no detalhe oficial; não são
completadas a partir da ementa, da proposição principal ou de uma apensada.
Para PEC cuja situação própria já confirma transformação em norma, o despacho
pode identificar a emenda somente quando começa com a declaração explícita
“Transformado na Emenda Constitucional N/AAAA.”; menções no restante do texto
não contam. O último andamento disponível pode ser anterior à data da coleta.

**Senado:** a [API oficial de processos](https://legis.senado.leg.br/dadosabertos/v3/api-docs)
aceita até 100 valores de `idProcesso` por consulta. O coletor usa cinco lotes para
os 462 IDs e consulta `/processo/<id>` quando precisa confirmar estados finais,
norma gerada ou informação incompleta. Usa `situacaoAtual`, `tramitando`, datas
publicadas e `normaGerada` do próprio processo. No detalhe, considera somente a
autuação principal para situações históricas; processos relacionados e outros
números não transferem seu resultado para o projeto consultado.

As classificações são conservadoras e preservam a descrição original:

- **Virou lei:** transformação explícita do próprio PL/PLP em norma legal ou
  referência normativa final direta. Aprovação e remessa à sanção não bastam.
- **Tramitando:** situação ativa reconhecida da Câmara ou indicação explícita de
  tramitação do Senado, sem estado terminal conflitante.
- **Arquivado/rejeitado:** situação final explicitamente informada pela fonte.
- **Emenda promulgada:** resultado normativo próprio de PEC, separado da contagem
  de leis, conforme a distinção da [Constituição, artigos 59 e 60](https://legis.senado.leg.br/norma/579494/publicacao/16434817).
- **Outras / sem classificação:** situação vazia, desconhecida, retirada,
  prejudicada ou transformada em outra proposição, quando não há prova de um dos
  resultados acima. A descrição oficial e a data continuam visíveis.

Cada item conserva `consultadoEm` (consulta), `atualizadoEm` (andamento informado),
fonte, descrição original e eventual norma gerada. `generatedAt` marca apenas a
montagem do snapshot. Falha de atualização mantém a consulta anterior e sua data,
com status parcial; a interface não inclui esse estado antigo nas contagens
confirmadas. Sem classificação de todos os itens, o cabeçalho informa cobertura
parcial e não transforma zero leis confirmadas em prova de que nenhuma virou lei.
Snapshots sem a nova coleta continuam válidos e mostram situação não consultada.

**Fotografia local consultada em 7/10/2026:**

| Casa | IDs consultados | Viraram lei | Emendas | Tramitando | Arquivados/rejeitados | Sem classificação confirmada |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Câmara | 19.878 | 149 | 1 | 16.876 | 675 | 2.177 |
| Senado | 462 | 2 | 0 | 441 | 0 | 19 |

Esses números contam projetos distintos dentro de cada casa; uma coautoria pode
aparecer em várias fichas. A coleta conseguiu ler todos os IDs, mas isso não torna
todas as situações classificáveis. Na Câmara, os casos sem classificação incluem
1.581 situações vazias, 389 retiradas, 197 devolvidas e dez transformações em nova
proposição. No Senado, são oito prejudicadas, seis retiradas, quatro remessas à
Câmara com tramitação encerrada no Senado e um processo sem situação confirmada.
Remessa à outra casa não comprova a situação atual no destino. O detalhe individual
prevalece sobre o arquivo anual quando consultado; ambos preservam suas datas reais
nos metadados. Esta fotografia e os caches são locais e não estão no Git.

### Comparar partidos

`/api/c/partidos` agrupa os cadastros atuais de deputados e senadores pela sigla da lista oficial. Para cada cargo informa quantos registros integram a lista, quantos têm notas importadas, gasto somado, média por parlamentar com notas e alertas (`pico` e `fornecedor`), além dos três maiores gastos do partido. Quem não tem nota importada não entra na média; partido sem nenhuma nota fica com gasto e média nulos. A tela soma a isso a presença média da Câmara, os votos por partido do catálogo do Placar (somente texto principal de PL, PLP e PEC; votação sem arquivo de detalhe fica sem maioria, nunca zero) e os dados coletados do Senado, sempre em linhas separadas por casa. Votações secretas ficam fora da comparação nominal. A unidade usa somente votos Sim/Não; a concordância entre pessoas usa escolhas nominais registradas para ambas. Presença do Senado é contagem de registros positivos, sem percentual de assiduidade nem classificação de faltas. Cota usa a sigla da lista atual; presença usa a sigla do respectivo snapshot e votos usam a sigla publicada na votação. Esses recortes podem divergir após mudanças de partido.

### Eleições de 2026 — TSE, consulta de 7/10/2026

```sh
make collect-elections            # baixa as candidaturas do TSE e completa nomes civis e nascimentos
python3 ingest/elections_2026.py   # reconstrói o snapshot sem rede, a partir do cache
make build
```

`ingest/elections_2026.py` liga cada nome da lista oficial atual (595 registros) a uma candidatura do
[arquivo de candidaturas de 2026 do TSE](https://dadosabertos.tse.jus.br/dataset/candidatos-2026). Nome civil e data de
nascimento vêm das APIs da Câmara (`/deputados/{id}`) e do Senado (`/senador/{codigo}`) e ficam só no cache local
`data/raw/tse/identidades-2026.json`; CPF não é lido nem guardado. A ligação usa a primeira regra que der uma única
candidatura: mesmo nome civil e nascimento; nomes com as mesmas palavras e nascimento (sobrenome a mais, iniciais abreviadas,
palavras juntas); nome de urna igual ao parlamentar, mesma UF e nascimento (nome social, grafia diferente); ou mesmo nome civil
e UF com ano de nascimento diferente em um ano (divergência entre fontes). Sem resposta única, a ficha não afirma nada.

No arquivo gerado pelo TSE em 07/10/2026 16:30:39 (1º turno), 551 dos 595 registros foram ligados (540 pela primeira regra,
6 pela segunda, 4 pela terceira e 1 pela quarta), sem ambiguidade. Os 44 restantes não têm candidatura correspondente no arquivo,
como senadores eleitos em 2022, com mandato até 2031; a ficha diz que a candidatura não foi encontrada, sem concluir que a
pessoa não concorreu. Dos 551, 347 aparecem como eleitos (por QP, por média ou majoritários), 125 como suplentes, 69 como não
eleitos, 6 no 2º turno de 25/10/2026 e 4 sem resultado no arquivo (`#NULO`). A ficha mostra um selo curto no cabeçalho e a frase
completa, com fonte, data e método, em "Fontes e datas". O 2º turno exige nova coleta depois de 25/10.

O snapshot `data/snapshots/eleicoes-2026.json` guarda só cargo, UF, número, nome de urna, partido, turno e situação de cada
candidatura ligada, além de fonte, método e cobertura. `/api/c/perfil/<id>` o anexa à ficha como `eleicao2026`.

## Quanto custa um mandato — Fase 1, levantamento em 7/10/2026

O [levantamento de fontes](mandate-cost-sources.md) registra URLs oficiais,
formatos, granularidade, histórico confirmado, atualização, termos, privacidade
e recomendação para a v1. É documentação para aprovação; não há novo coletor,
migração, soma financeira nem alteração da ficha nesta fase.

A leitura local confirmou cota para **509/513 deputados e 79/82 registros do
Senado**, gabinete com valor e meses para **512/513 deputados e 0/82 senadores**.
No gabinete da Câmara, **503** têm janeiro–julho de 2026; **9** têm somente parte
desse intervalo e **1** não tem valor mensal. A atualização da página em outubro
não transforma esses dados em despesas até outubro. A referência salarial se
aplica aos dois cargos (513 e 82 registros), mas não comprova pagamento individual.
Auxílios, ocupação de imóvel e folha individual têm **0 pessoas integradas como
componentes próprios em ambas as Casas**; isso não significa gasto zero.

A Câmara tem amostra oficial de folha por deputado/mês e consulta de moradia.
O Senado publica folha mensal e relatório atual de moradia, mas a atribuição
reproduzível de pagamentos e equipe por pessoa/competência exige validação.
O relatório atual de moradia informa opção/ocupação, não uma série de pagamentos.
A v1 proposta preserva essas diferenças: subsídio de referência fora do total
pago, imóveis sem valor imputado, benefícios sem duplicar folha/cota e comparação
somente com mesmas partes e períodos. Detalhes e condições estão no levantamento.

## Quanto custa um mandato — Fase 2: coleta local

A coleta de folha da Fase 2 terminou com 4.617 competências consultadas (513 deputados × 9 meses): 1.014 completas, 3.512 parciais e 91 indisponíveis. A [tabela mensal e os três exemplos auditados](mandate-cost-collection.md) detalham cota, gabinete, folha e moradia, incluindo suplementares e divergências entre fontes.

Os [resultados e exemplos da coleta](mandate-cost-collection.md) documentam a
folha individual e moradia da Câmara, o inventário de folhas suplementares e o
piloto interrompido do Senado. Os snapshots novos são locais e **ainda não são
consumidos pela ficha, comparação, lista ou API**. O SQLite não foi modificado.
Cota e gabinete são reaproveitados com suas próprias datas e competências.

```sh
make collect-mandate-cost YEAR=2026   # rede explícita, janeiro–setembro
make audit-mandate-cost YEAR=2026     # reconstrução offline
```

Folha: no máximo duas consultas simultâneas, intervalo mínimo de 0,25 segundo
entre inícios, resposta gravada atomicamente por pessoa/mês. Moradia: consultas
sequenciais e cache por página/mês. Retomadas pulam respostas válidas, repetem
falhas e preservam observações anteriores com suas datas. Há centavos inteiros,
fontes, competências e hashes; não há rateio de folhas anônimas ou anualização.
As páginas individuais podem conter normal, complementar e adiantamento de 13º;
todas as tabelas observadas são mantidas. Inventários CSV preservam somente
agregados do grupo parlamentar, sem dados de servidores ou códigos por pessoa.

Moradia tem **4.597 registros pessoa/mês com valores publicados de 4.617
possíveis** (513 × 9): 507 por mês em janeiro–março, 511 em abril e 513 por mês
em maio–setembro. Os 20 ausentes ficam nulos. Setembro tem zeros publicados de
auxílio/complemento para todos, mas a folha de Rui Falcão informa auxílio; isso
é uma divergência entre fontes, não prova de que ninguém recebeu benefício.

No Senado, o CSV mensal não oferece nome/identificador individual seguro:
**10 IDs selecionados, 0 ligações, 0 competências validadas, 0 consultas
individuais**. A validação parou no esquema e o coletor final guarda somente
cabeçalhos/metadados, sem linhas de servidores. O subsídio permanece referência.

A proposta de período comum é **janeiro–julho de 2026**, condicionada à presença
das mesmas partes em cada mês. Folhas com cobertura mensal não certificada,
lacunas e divergências continuam explícitas. Nenhuma média é liberada nesta
fase; comparações futuras exigem mesma Casa, partes e competências. O auxílio
já observado na folha não será somado novamente como moradia. Complementos
com sinais diferentes permanecem separados até conciliação contábil comprovada.

## Quanto custa um mandato — Fase 3: composição mensal da Câmara

As [verificações A–C](mandate-cost-preflight.md) documentam o efeito das linhas
negativas de complemento, o exercício efetivo e a fonte única dos auxílios.
O [relatório da cota](mandate-quota-audit.md) detalha a reconciliação com o ZIP.
A [auditoria de privacidade](mandate-privacy-audit.md) registra a ocorrência
remanescente no log do Codex e o comando utilizado; não se declara ausência
absoluta de registros em todos os logs.

```sh
python3 ingest/chamber_service.py --collect --year 2026 --months 1-9
python3 ingest/chamber_service.py --year 2026 --months 1-9  # offline
python3 ingest/chamber_quota_audit.py                      # offline, banco somente leitura
python3 -m ingest.mandate_cost_composition                 # offline
make build
```

`chamber-service.json` projeta os períodos oficiais de exercício para cada mês,
com fonte e dias. Os 513 históricos foram validados. Gilmar Machado entrou em
exercício em 15/09/2026; janeiro–julho fica fora do mandato. Afastamentos e retornos
não são substituídos pela duração nominal da legislatura.

`mandate-cost.json` serve apenas a ficha da Câmara, via `mandateCost` em
`/api/c/perfil/<id>`. O principal é a média mensal dos meses de janeiro–julho em
exercício com as quatro partes no mesmo mês: remuneração bruta de todas as tabelas
da página individual (sem o 13º), auxílios da folha, cota sem a categoria de
complemento de moradia e gabinete. O 13º aparece à parte. Os valores permanecem
em centavos inteiros, inclusive negativos publicados. A consulta de moradia nunca
fornece dinheiro para a soma; divergências são apenas registradas. Não se soma
referência salarial a pagamento.

A página individual de remuneração é o registro da pessoa; o inventário anônimo
de folhas suplementares é só nota de rodapé ([regra revisada](mandate-cost-preflight.md)).
A cota exige igualdade da fotografia importada com o arquivo oficial, e o gabinete
exige seção importada completa. Parte ausente ou exercício desconhecido tira o mês
da média; mês sem nota de cota não vira zero. Sem mês elegível, não há número
principal. Não há nova média geral, comparação entre Casas, ranking ou ordenação.

Nesta fotografia, 508/513 deputados têm média mensal; 452 com os sete meses. Os
5 sem principal estão listados nas verificações.

Desde o esquema v3 (8/10/2026), as linhas `COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA` da
CEAP da Câmara têm natureza `complemento_moradia`: ficam fora do total, da média,
da lista e dos alertas da cota, aparecem à parte na ficha com o sinal publicado e
continuam na exportação de notas. A migração roda ao iniciar o servidor ou com
`make db-init`; faça `make db-backup` antes.

O Senado continua com cota e referência do cargo, sem novo total;
a consulta individual existe oficialmente, mas o piloto não validou pagamentos
individuais nesta base.

## Quanto custa um mandato — período do mandato (2023–2025), partes baratas

Primeira coleta para trocar o recorte de jan–jul/2026 pelo mandato atual (desde
fev/2023). Fontes e limites no [levantamento](mandate-period-sources.md). Só a
Câmara, só os deputados da lista atual e sem folha individual, que fica para uma
etapa própria. Nenhum desses arquivos altera a ficha, a média ou o SQLite.

```bash
make collect-mandate-history
```

- **Cota:** `ingest/legislative.py --year {ano} --output data/raw/legislative/history/legislative-{ano}.json`. Fica fora de `data/imports/`: o `make import` importa tudo dessa pasta, e a fonte `camara_ceap` de outro ano substituiria a de 2026.
  O `legislative.json` do ano corrente não é tocado.
- **Moradia:** `ingest/chamber_housing.py --year {ano}` grava
  `data/snapshots/chamber-housing-{ano}.json`; 2026 continua em `chamber-housing.json`.
- **Gabinete e presença:** `ingest/chamber_mandate_history.py` lê o perfil anual
  (`/deputados/{id}?ano={ano}`, mesmo parser da ficha) e a página de presença em
  Plenário (`/deputados/{id}/presenca-plenario/{ano}`), e grava
  `data/snapshots/chamber-mandate-history.json` com valores por mês desde 2023-02.
  O cache em `data/raw/mandate-history/` guarda só o extrato do gabinete e
  datas/status da presença, sem HTML.

Valores da época, sem correção pela inflação. Mês ausente é dado não publicado ou
não coletado, nunca zero.

Cobertura da coleta de 8/10/2026 (513 deputados da lista atual):

| Parte | Resultado |
| --- | --- |
| Cota | Arquivos de 2023, 2024 e 2025 importados (175.140, 174.699 e 171.081 notas da Câmara, todas as pessoas) |
| Moradia | Todos os meses de fev/2023 a dez/2025 consultados com status `available` |
| Gabinete | 503 deputados com algum mês; por mês, 478 a 498. **Dez/2024: 0** — a fonte não publica o mês para ninguém |
| Presença | 502 deputados com algum mês; por mês, 444 a 481. Janeiro sem sessões (recesso), não é ausência |

Os 10 sem gabinete e os 11 sem presença são, em geral, suplentes que entraram
depois de 2025; os nomes estão no snapshot.

### Média sobre o mandato (desde 8/10/2026)

`mandate-cost.json` (esquema 3) passou a cobrir fev/2023–jul/2026: 2023–2025 vêm
dos arquivos por ano da seção anterior, mais `chamber-payroll-{ano}.json` (folha
individual) e `chamber-service-{ano}.json` (exercício, reconstruído offline do
mesmo histórico em cache). 2026 segue a regra da Fase 3. Mesmas exigências por
mês: exercício confirmado e as quatro partes.

```sh
for year in 2023 2024 2025; do python3 ingest/chamber_service.py --year $year --months 1-12; done
python3 ingest/chamber_payroll.py --collect --year 2023 --months 2-12 --output data/snapshots/chamber-payroll-2023.json
python3 ingest/chamber_payroll.py --collect --year 2024 --months 1-12 --output data/snapshots/chamber-payroll-2024.json
python3 ingest/chamber_payroll.py --collect --year 2025 --months 1-12 --output data/snapshots/chamber-payroll-2025.json
python3 -m ingest.mandate_cost_composition
```

Única exceção: **dezembro/2024 sem verba de gabinete**, lacuna da própria fonte
para todos os deputados. O mês entra na média com o gabinete vazio
(`sourceGapMonths`), e a média do gabinete usa os demais meses. O principal é a
soma exata das médias de cada parte, arredondada para baixo uma vez; sem lacuna,
é idêntico à média das somas mensais (conferido: as 513 médias de jan–jul/2026
ficaram iguais). Valores da época, sem correção pela inflação, com essa frase na
ficha.

Resultado em 8/10/2026: **510/513 deputados com média** (antes 508), 376 com os 42
meses e mediana de 42 meses usados. Dez/2024 entra com o gabinete vazio para 474.
Os 3 sem média não têm mês com as quatro partes. O leitor da folha passou a
reconhecer a "Folha de gratificação natalina" de dezembro (13º, fora da média);
antes ela bloqueava o mês.

`mandate-cost.json` (esquema 4) é compacto: cada link aparece uma vez em `urls` e
os meses guardam o índice; campos vazios e as partes de meses fora do mandato não
são gravados. `backend.profiles.expand_mandate_cost` devolve o formato completo
antes de responder, então a API e a ficha não mudam (conferido: zero diferenças
contra o formato anterior). ~15,5 MB no disco e ~105 MB de memória ao carregar,
contra 31 MB e ~180 MB sem compactar.

### Cota e presença da Câmara no mandato inteiro (desde 8/10/2026)

A cota e a presença da Câmara nas telas (lista, ficha, comparação, home, partidos
e presença) cobrem o mandato, desde fev/2023. A cota do Senado segue o mesmo recorte
(desde 8/10, fontes `senado_ceaps_{ano}`). Votações nominais e autoria do Senado também cobrem desde fev/2023 na implementação local de 9/10; a presença segue em 2026. Para quem
tem mandato iniciado antes (senadores eleitos em 2018), a ficha avisa que a cota conta a
partir de fev/2023.

- **Cota no SQLite (esquema v5):** as notas de 2026 seguem uma a uma em
  `expenses`. De fev/2023 a dez/2025 (Câmara e Senado), o banco guarda as notas em
  formato enxuto em `quota_history_notes` (pessoa, mês, data, categoria, valor,
  fornecedor e link da nota; sem número do documento e demais colunas). A visão
  `quota_history` devolve as mesmas colunas de `expenses`. Cada Casa e ano é uma
  fonte própria (`camara_ceap_2023`, `senado_ceaps_2023` etc.) e não substitui as
  fontes de 2026. São 574.455 notas, 59 MB; o banco local foi de 84 MB para 142 MB.
  A v4 guardava só totais por mês, fornecedor e maiores notas; a v5 os substitui
  pelas notas (decisão de 8/10: aceitar o peso para ter lista de notas e CSV do
  mandato), e os 837 totais por pessoa ficaram idênticos.
  ```sh
  python3 ingest/quota_history.py   # data/raw/legislative/history → data/imports-history
  make db-backup && python3 -m backend.quota_history
  ```
  `data/imports-history/` fica fora de `data/imports/` de propósito: `make import`
  continua importando só o ano corrente.
- **Média mensal:** lista, comparação, partidos, home e o cartão de cota usam o gasto
  médio por mês, `total ÷ meses com notas` (`authority_totals.monthCount`). Mês sem
  nota é ausência de dado, não gasto zero, então licenças e trocas de suplente não
  diluem a média. Assim deputados e senadores ficam comparáveis, os dois desde fev/2023.
  A ficha mostra também o total e o período.
- **Notas do mês:** na ficha da Câmara, a fonte da cota de cada mês do mandato abre a lista
  das notas daquele mês (`/api/c/notas?id=camara:<id>&mes=AAAA-MM`), com link para
  cada nota original, o total e como achar o mesmo total no arquivo anual (filtrar
  `ideCadastro` e `numMes` e somar `vlrLiquido`). A página do deputado na Câmara não
  serve de fonte: o gráfico dela inclui passagens aéreas, que ficam fora do arquivo
  aberto. O CSV da ficha traz todas as notas desde fev/2023; nas de 2023–2025 a
  coluna Documento fica vazia.
- **Alertas:** picos e concentração avaliam o mandato inteiro, nas duas Casas (regra,
  cobertura e prazos em [Alertas](alerts.md)); lançamentos de valor alto seguem só em 2026.
- **Senado, presença pelo Diário no mandato (9/10/2026):** `make collect-senate` lê as listas de presença das
  sessões deliberativas de fev/2023 até hoje (PDFs do Diário; requer `ingest/senate-requirements.txt`). Na
  primeira coleta: 296 de 301 sessões deliberativas da agenda com tabela validada; as outras ficam de fora,
  sem virar falta. Os nomes são ligados a todos os senadores do banco (inclui quem saiu), mais duas grafias
  fixas do Diário conferidas à mão; 22 registros ficam sem ligação (ministros sem cadastro de senador e erros
  de leitura do PDF). Cada pessoa mostra as sessões com presença registrada e, pelo histórico de exercício,
  quantas sessões com lista validada caíram nos seus períodos em exercício. Sem faltas nem percentual.
- **Senado, participação nas votações nominais e licenças:** para o mandato, `make collect-senate-participation`
  usa as votações nominais públicas já coletadas e o histórico de exercício: por sessão com votação nominal
  em que a pessoa estava em exercício, votou ou presidiu, presente sem votar, ausência com motivo registrado
  pelo Senado (atividade parlamentar, missão, licença), não compareceu ou sem registro (que não vira falta).
  O Regimento (art. 13, § 2º) pede que quem está presente participe das votações nominais. As licenças vêm de
  `/senador/{codigo}/licencas`, desde fev/2023, com data e tipo. O cartão "Trabalha?" traz o resumo; a seção
  "Mandato", o detalhe e as licenças por tipo.
- **Lista de políticos:** o valor principal é o custo médio por mês da própria Casa, o mesmo do "Quanto
  custa?" da ficha (`backend/costs.py`): na Câmara, salário bruto, auxílios, cota e verba de gabinete nos
  meses com as quatro partes; no Senado, remuneração, equipe do gabinete e cota nos meses com as três. A
  linha diz quantos meses entram na média e mostra a cota à parte. As Casas não publicam as mesmas partes:
  "Quem mais custa" com "Todos" mostra dois blocos (Câmara e Senado), cada um ordenado por dentro, e a
  barra e o "acima da média" comparam só com a mesma Casa. Sem mês com todas as partes, "Sem custo", sem
  estimativa; quem está nessa situação vai para o fim da ordem, pela cota.
- **No cargo desde:** o cabeçalho da ficha diz "Na Câmara desde 2007" ou "No Senado desde 2019", o início
  da sequência ininterrupta de legislaturas (Câmara) ou mandatos (Senado) com exercício até o atual; um
  mandato anterior separado por um intervalo não entra. `make collect-tenure` gera `tenure.json` a partir do
  histórico de cada deputado(a) (`/deputados/{id}/historico`, com o registro "no início da legislatura"
  antes de 2003, quando a Câmara não publica a situação) e do histórico de mandatos do Senado.
- **Equipe e verba de gabinete no Senado:** a seção mostra a equipe comissionada do gabinete no mês mais
  recente e a média do mandato, da mesma folha do cartão de despesas; não é comparável à verba da Câmara.
- **O que segue em 2026:** fornecedores globais (`supplier_totals`) e a presença do Senado.
- **Presença:** `presenca.json` agora soma o mandato (fev/2023 até o mês corrente),
  com `inicio` e `fim` por deputado, e vem de `ingest/chamber_mandate_history.py`
  (que reconsulta o ano corrente a cada `--collect`). Conferência em 8/10: a parte de
  2026 bate dia a dia com o snapshot anterior nos 512 deputados com dados.

A média mensal da cota na lista (meses com notas) e a parte "cota" do custo do
mandato (meses em exercício com as quatro partes) usam recortes diferentes e podem
diferir um pouco; cada uma diz o seu período.

## Minha cidade — Fase 1: IBGE e TSE

```sh
make collect-cities              # coleta manual; downloads podem ser grandes
python3 ingest/cities.py          # reconstrói o snapshot sem acessar a rede
make build
```

A página usa a mesma base nacional para todas as localidades. O catálogo vem da
[API de localidades do IBGE](https://servicodados.ibge.gov.br/api/v1/localidades/municipios),
com código IBGE, nome e UF. População é um conjunto separado: a API de localidades
não informa habitantes. População ausente permanece nula, com fonte e ano próprios.
Brasília e Fernando de Noronha constam no cadastro do IBGE, mas não elegem prefeito
nem vereadores; suas páginas explicam a diferença administrativa.

O cruzamento utiliza a
[tabela oficial de códigos TSE e IBGE](https://dadosabertos.tse.jus.br/dataset/codigos-oficiais-de-uf-e-municipios-segundo-o-tse-e-o-ibge).
Código TSE nunca é tratado como se fosse código IBGE. As candidaturas vêm dos
arquivos `consulta_cand_2024.zip` e `consulta_cand_2026.zip` do TSE; situação eleitoral
é a publicada em `DS_SIT_TOT_TURNO`. A tela descreve resultados eleitorais, não uma
certificação de exercício atual: pode haver substituições, decisões judiciais e
novas eleições depois da fotografia consultada. Resultados de 2026 não antecipam
os mandatos de 2027. Ausência de eleitos confirmados não vira zero representantes.

A lista federal atual vem do roster já importado da Câmara e do Senado, com sua
própria fonte e data. A ligação de eleitos de 2026 às fichas exige nome civil ou de
urna normalizado, UF e cargo iguais e correspondência única nos dois sentidos.
Nomes abreviados, grafias divergentes, troca de cargo, candidaturas sem ficha e
homônimos podem permanecer sem link. Não se reutiliza o cache de nascimento do
coletor anterior; CPF, título, e-mail e nascimento não entram nesta funcionalidade.

O recorte de mais votados inclui apenas candidatos a deputado federal confirmados
como eleitos no estado. Mostra votos nominais observados no município, não votos
no estado nem votos de legenda. A restrição a eleitos evita dar destaque a pessoas
não eleitas e fica explícita na interface. Isso não é uma lista de todos os
candidatos que receberam votos na cidade.

Foi escolhido um snapshot local em vez de novas tabelas SQLite: os dados são uma
fotografia de consulta por município, não participam dos agregados de despesas e
podem ser substituídos sem migração ou reimportação parlamentar. O servidor carrega
o snapshot sob demanda e entrega só a cidade selecionada. Caches, downloads,
snapshots e capturas de revisão ficam fora do Git.

Bens declarados e financiamento de campanha ficam para uma etapa posterior: será
necessário validar os respectivos leiautes, períodos, unidades monetárias (centavos)
e junções por identificador de candidatura, mantendo a mesma projeção de privacidade.
Emendas e contas municipais são descritas nas seções das Fases 2 e 3 abaixo.

### Cobertura verificada em 7/10/2026

| Conjunto | Cobertura observada |
| --- | ---: |
| Localidades do cadastro IBGE, com população de 2026 | 5.571 |
| Localidades com correspondência oficial TSE–IBGE | 5.571; nenhuma sem correspondência |
| Eleitos municipais nas eleições ordinárias de 2024 | 69.213 |
| Prefeitos / vice-prefeitos / vereadores | 5.530 / 5.530 / 58.153 |
| Localidades com algum eleito municipal confirmado | 5.568 |
| Eleitos de 2026 nos cargos estaduais, distritais e federais considerados | 1.666, nas 27 UFs |
| Governadores / vices / deputados estaduais / distritais | 20 / 20 / 1.035 / 24 |
| Deputados federais / senadores eleitos em 2026 | 513 / 54 |
| Localidades com votos nominais observados para deputados federais eleitos | 5.571 |
| Eleitos federais ligados às fichas da lista parlamentar atual | 288 de 567 |

O cadastro inclui os 5.569 municípios, Brasília e Fernando de Noronha. A diferença
em relação ao planejamento de 5.570 localidades é Boa Esperança do Norte/MT
(IBGE `5101837`, TSE `73709`), presente nas fontes oficiais consultadas. População
vem da [tabela 6579, variável 9324, período 2026 do IBGE](https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/2026/variaveis/9324?localidades=N6%5Ball%5D),
com valor observado para todas as localidades. Na Fase 3, as comparações financeiras
usam a população do exercício correspondente, como descrito adiante.

Brasília e Fernando de Noronha não têm eleição municipal. Iporá/GO não tem eleitos
confirmados no recorte ordinário do arquivo consultado; a página mantém população,
eleição estadual e representação federal, com aviso de ausência municipal.
Outros municípios têm vereadores confirmados, mas não prefeito e vice: ao todo,
39 dos 5.569 municípios não têm prefeito eleito confirmado neste recorte.
Não se infere o motivo jurídico dessa ausência nem se preenche com resultados
suplementares. As 7 UFs sem governador eleito confirmado de 2026 mantêm os demais
cargos e o aviso de resultado ausente para o Executivo.

Os 279 eleitos federais sem link continuam listados: 265 não têm nome civil ou de
urna exatamente correspondente no roster da mesma UF; 14 têm nome correspondente,
mas cargo diferente. Isso pode refletir novos eleitos, variações de nome ou mudança
de cargo; não é prova de que sejam pessoas diferentes ou que não exista ficha.
Os 595 registros do roster atual continuam disponíveis em suas UFs, independentemente
dessa ligação. Falha de atualização do roster mostra a lista anterior com aviso
junto à fonte e não comprova que a fotografia esteja atualizada.

### Recorte, leiautes e reconstrução

Os `leiame.pdf` dos arquivos anuais foram conferidos: `SG_UE` é código TSE de
município nas candidaturas municipais; `CD_MUNICIPIO` é o código TSE no arquivo de
votos; `SQ_CANDIDATO` identifica a candidatura. Só os estados `ELEITO`,
`ELEITO POR QP` e `ELEITO POR MÉDIA` entram. O turno mais recente da mesma
candidatura prevalece independentemente da ordem das linhas.

O arquivo de 2024 também contém eleições suplementares realizadas posteriormente.
Para não misturar pleitos e apresentar dois prefeitos na mesma cidade, a seleção
exige `CD_TIPO_ELEICAO = 2`, `NM_TIPO_ELEICAO = ELEIÇÃO ORDINÁRIA` e datas de
6/10 ou 27/10/2024; em 2026, 4/10 ou 25/10/2026. A fotografia atual de 2026 é do
primeiro turno e deve ser recoletada após o segundo. A lista de 2024 não é uma
reconstituição congelada do dia da apuração: conserva a situação publicada na
consulta, que pode refletir alterações posteriores do TSE.

As novas candidaturas são baixadas em memória e imediatamente reduzidas a uma lista
permitida de campos eleitorais. Apenas os eleitos são gravados nos caches
`data/raw/tse/candidacies_2024_v2.jsonl` e `candidacies_2026_v2.jsonl`; identificadores
federais sem nome são guardados à parte para conferir a consistência dos votos.
O ZIP de 2026 preexistente pode ser lido com a mesma projeção. Nenhum novo ZIP bruto
de candidaturas, CPF, título, nascimento ou e-mail é gravado pelo coletor.

O [arquivo de votos por município e zona de 2026](https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2026.zip)
consultado tem 448.161.667 bytes. A leitura percorre os CSVs estaduais linha a linha,
sem somar novamente os arquivos nacionais duplicados. Agrega primeiro turno por
município e candidatura, preferindo `QT_VOTOS_NOMINAIS_VALIDOS` quando a coluna existe
e usando `QT_VOTOS_NOMINAIS` apenas no leiaute sem aquela coluna. Não mistura os dois
campos. Exibe até dez eleitos com votos positivos, incluindo empates na última
posição; empates usam nome em ordem alfabética. Totais ausentes ou inválidos em uma
zona impedem publicar como completo o agregado daquela candidatura/município.
Nesta leitura não houve totais inválidos, candidatos desconhecidos nem códigos
municipais sem correspondência. Foram identificadas 6.749 candidaturas federais
não eleitas nos votos, excluídas do destaque público.

`--collect` completa caches; `--collect --refresh` atualiza fontes já guardadas.
Sem `--collect`, não há chamadas de rede. Respostas IBGE vazias ou inválidas não
substituem caches válidos; uma falha de atualização mantém os dados anteriores e
seu aviso. População de período anterior não substitui um cache mais recente por
falha temporária. Se um cache necessário a um snapshot já preenchido desaparecer,
a reconstrução é recusada, preservando o snapshot; restaure o cache ou execute a
coleta. O snapshot não agenda atualizações.

## Minha cidade — Emendas parlamentares (Fase 2)

A fonte é o [download nacional do Portal da Transparência](https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares),
com [dicionário oficial por emenda](https://portaldatransparencia.gov.br/dicionario-de-dados-emendas-parlamentares).
O endpoint público `/download-de-dados/emendas-parlamentares/UNICO` redireciona para
[EmendasParlamentares.zip](https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/emendas-parlamentares/EmendasParlamentares.zip).
A coleta de 7/10/2026 recebeu 32.447.704 bytes, com `Last-Modified` de 1/10/2026.
A tabela `EmendasParlamentares.csv` usa Windows-1252 e separador ponto e vírgula.
O ZIP fica em memória; só os campos públicos necessários da tabela por emenda são
projetados no cache. As outras tabelas, inclusive a de favorecidos com
identificadores de pessoas, não são processadas nem salvas pelo coletor.

### Recorte e interpretação

A interface usa **ano da proposta 2026**, não ano do pagamento. Os valores são a
execução acumulada publicada na fonte: empenhado, pago e restos a pagar pagos
permanecem separados, em centavos inteiros. Empenho não comprova pagamento; restos
a pagar não são somados ao campo pago. Ausência ou valor inválido torna o agregado
daquela natureza indisponível, sem preencher com zero. Ajustes negativos válidos
são preservados.

Cada linha da tabela é um desdobramento por emenda, localidade e classificação
orçamentária. Não se deduplica apenas pelo código da emenda: isso perderia valores
legítimos. A leitura das 5.634 linhas de 2026 reconcilia com o painel nacional
consultado: **R$ 40.060.378.330,46 empenhados** e **R$ 25.878.742.486,65 pagos**.
Esses totais incluem destinos sem código municipal e não são atribuídos às cidades.
A tabela por favorecido não é somada à tabela por emenda, evitando duplicação de
fluxos. No detalhe, linhas da mesma emenda, autoria e tipo podem ser agrupadas.

Só há associação quando `Código Município IBGE` consta no catálogo nacional de
5.571 localidades. Não se deduz destino pelo nome, UF, endereço de favorecido ou
área de atuação parlamentar. A localidade da emenda vem da regionalização
orçamentária; não representa todos os gastos federais nem necessariamente o
endereço do destinatário final.

Transferências especiais são identificadas exclusivamente pelo tipo oficial
`Emenda Individual - Transferências Especiais`. O bloco “Pix” é um subconjunto já
incluído no total, nunca uma parcela adicional. Não se infere esse tipo pelo nome
da autoria ou por valores.

A ligação às fichas compara o nome público exato normalizado com o **roster nacional
atual**, com unicidade nos dois sentidos. O catálogo de autorias inclui também as
linhas sem destino municipal; códigos com nomes conflitantes ficam sem ligação.
Não se usa a UF de destino como UF do autor nem se confunde o código de autoria
SIAFI com o identificador da Câmara ou do Senado. Bancadas, comissões e relatorias
não são ligadas a uma pessoa. Sem correspondência, permanece o nome da fonte.

### Coleta e reconstrução

```sh
make collect-amendments YEAR=2026
python3 ingest/amendments.py --collect --refresh --year 2026
python3 ingest/amendments.py --year 2026
```

Sem `--collect`, a reconstrução é local e não faz rede. O cache nacional contém
anos de proposta de 2014 a 2026; `--year` escolhe um recorte para o único snapshot
`data/snapshots/amendments.json` servido pela tela. Não há atualização agendada.
O snapshot independente mantém a API municipal sem alteração de esquema SQLite.
Caches e snapshots não entram no Git. Falhas preservam a base útil anterior;
a interface indica fotografia anterior quando uma atualização falha.

### Cobertura verificada em 7/10/2026

| Medida do recorte de propostas de 2026 | Cobertura |
| --- | ---: |
| Localidades com página e tratamento de ausência | 5.571 |
| Localidades com emendas e código municipal identificado | 511 |
| Localidades sem registro municipal identificável | 5.060 |
| Linhas com município identificado / linhas nacionais | 716 / 5.634 |
| Linhas com código `Sem informação`, excluídas do recorte municipal | 4.918 |
| Linhas de transferências especiais com município identificado | 135 |
| Localidades com transferências especiais identificadas | 119 |
| Autorias individuais nas linhas municipais / coletivas | 295 / 8 |
| Autorias municipais ligadas a fichas atuais | 281 |
| Individuais sem nome exato no roster / com nomes conflitantes | 13 / 1 |

As oito autorias coletivas permanecem sem ficha pessoal. A unicidade foi conferida
nas 630 autorias nacionais de 2026, incluindo 592 individuais e 38 coletivas;
561 individuais têm correspondência no roster, mas apenas 281 aparecem nas linhas
com destino municipal identificável. Nenhum vínculo depende da UF do destino.
A cobertura eleitoral da Fase 1 não mudou: 69.213 eleitos municipais, 1.666 gerais
e 288 eleitos federais ligados a fichas atuais.

As linhas municipais somam R$ 1.352.830.217,02 empenhados e R$ 646.802.169,64 pagos.
O subconjunto de transferências especiais soma R$ 236.162.367,48 empenhados e
R$ 169.685.593,49 pagos. Dos 678 registros nacionais desse tipo, 543 não identificam
município e ficam fora da distribuição municipal. A contagem de 120 valores distintos
no campo municipal inclui o marcador `Sem informação`; há 119 códigos válidos.

São Paulo/SP tem três emendas de três autores, R$ 1.884.410,26 empenhados e
R$ 499.934,88 pagos, sem transferências especiais identificadas neste recorte.
Serra da Saudade/MG não tem linha com destino municipal identificado para 2026;
a tela explica a ausência. Nenhum desses resultados comprova o total recebido
pelo município. A distribuição municipal incompleta é a principal limitação desta
fase; os valores sem destino não são rateados nem atribuídos por inferência.

## Minha cidade — Contas municipais (Fase 3)

Fontes oficiais: [DCA/SICONFI — conjunto de dados](https://www.tesourotransparente.gov.br/ckan/dataset/api-dca-entes),
[documentação da API](https://apidatalake.tesouro.gov.br/docs/siconfi/),
[esquema dos endpoints](https://apidatalake.tesouro.gov.br/docs/siconfi.yaml),
[FINBRA — consulta nacional](https://siconfi.tesouro.gov.br/siconfi/pages/public/consulta_finbra/finbra_list.jsf)
e [instruções de preenchimento](https://www.siconfi.tesouro.gov.br/siconfi/pages/public/conteudo/conteudo.jsf?id=42).
O recorte inicial é o **exercício encerrado de 2025**, disponível em 7/10/2026.
Não mistura o exercício de 2026 ainda em andamento, nem substitui lacunas de uma
cidade por valores de anos diferentes.

### Indicadores e limites

| Indicador | Anexo e seleção da fonte |
| --- | --- |
| Receita bruta realizada | I-C, rótulo `Padrão`, conta `TotalReceitas`, coluna `Receitas Brutas Realizadas` |
| Despesa empenhada total | I-D, `Padrão`, `TotalDespesas`, `Despesas Empenhadas` |
| Saúde, exceto intraorçamentárias | I-E, `Total Geral da Despesa por Função`, `TotalDespesas`, conta `10 - Saúde`, `Despesas Empenhadas` |
| Educação, exceto intraorçamentárias | I-E, `Total Geral da Despesa por Função`, `TotalDespesas`, conta `12 - Educação`, `Despesas Empenhadas` |
| Pessoal e encargos, exceto intraorçamentárias | I-D, `Padrão`, `DO3.1.00.00.00.00`, `Despesas Empenhadas` |

Os nomes completos dos anexos na API têm prefixo `DCA-Anexo`. O total de receita
bruta é anterior às deduções de FUNDEB e outras deduções. Receita e despesa totais
incluem operações intraorçamentárias, conforme os agregados publicados; não são
uma medida líquida consolidada sem essas operações. Saúde e educação não incluem intraorçamentárias no detalhamento por função.
Pessoal usa explicitamente a natureza ordinária, excluindo intraorçamentárias. Esse indicador não é a despesa
com pessoal calculada para o limite da LRF.

Saúde e educação são funções; pessoal é uma natureza de despesa que pode estar
contida nessas funções. Não se somam recortes sobrepostos, totais com seus filhos,
nem empenhado com liquidado ou pago. Todos os valores de despesa usam a mesma
etapa: empenhado. Valores monetários são lidos com precisão decimal e guardados
em centavos inteiros. Campo ausente, inválido ou conflitante permanece ausente;
zero só aparece quando efetivamente publicado na fonte.

O endpoint DCA é
`https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt/dca?an_exercicio=2025&id_ente=CODIGO_IBGE`.
A API exige o ente, retorna até 5.000 linhas por página e informa `hasMore` e
links de paginação. O limite oficial é uma requisição por segundo. Uma resposta
sem ente não constitui uma base nacional. O extrato de entregas identifica
`Balanço Anual (DCA)`, período 1, com estados homologado (`HO`) ou retificado (`RE`).
Ausência de linhas financeiras ou falha de rede, sozinha, não comprova falta de entrega.
A classificação de não entrega exige consulta completa ao extrato e identidade
confirmada no cadastro oficial `/entes` (código, UF e esfera municipal) ou em
registro válido do próprio extrato. O cache de entes descarta CNPJ e mantém apenas
código, nome, UF e esfera. Código sem identidade confirmada permanece indisponível.

Brasília não recebe os valores do Governo do Distrito Federal (código SICONFI 53)
como se fossem contas de uma prefeitura. Fernando de Noronha também não é um
município com DCA própria neste recorte. Ambos têm explicação e ficam fora das
medianas e dos denominadores municipais.

### Comparação por porte

As faixas seguem as classes de tamanho populacional usadas pelo IBGE na
[Pesquisa de Informações Básicas Municipais](https://agenciadenoticias.ibge.gov.br/media/com_mediaibge/arquivos/070e55d231118f7c5e02f77187bad04e.pdf):
até 5.000; 5.001–10.000; 10.001–20.000; 20.001–50.000; 50.001–100.000;
100.001–500.000; mais de 500.000 habitantes.
A população vem das [estimativas municipais de 2025, tabela 6579 do IBGE](https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/2025/variaveis/9324?localidades=N6%5Ball%5D),
com 5.571 localidades. Ela é independente da população de 2026 no cabeçalho da página.

A mediana considera os demais municípios brasileiros da mesma faixa, excluindo a
cidade consultada, Brasília, Fernando de Noronha e observações sem valor válido.
Cada indicador informa seu próprio tamanho de amostra; no mínimo três pares são
necessários. Valores declarados iguais a zero entram no cálculo. Não há ranking,
percentil, pontuação nem juízo de eficiência. A mediana não é uma meta de gasto.

A tela compara **valores por habitante**: cada valor do exercício dividido pela
população do mesmo ano (IBGE 2025), arredondado ao centavo, contra a mediana dos
valores por habitante dos pares (`perCapitaCents`, `perCapitaMedianCents`,
`perCapitaSampleSize`). As faixas são largas (por exemplo, “mais de 500 mil”
vai até São Paulo), então comparar totais fazia o tamanho da cidade decidir o
resultado. Exemplo: Guarulhos tem gasto total acima da mediana da faixa, mas
gasta R$ 5.164 por morador, cerca de 16% abaixo do típico (R$ 6.176). As
medianas de totais continuam na API. Sem população válida, não há valor por
habitante nem comparação. Na tela, diferenças menores que 10% aparecem como
“parecido com o típico”.

As comparações só são liberadas após a confirmação de cobertura nacional completa.
A seção indica também a fonte e a data da base nacional usada nas medianas.
Esse indicador mede cobertura, não atualização: uma falha de atualização preserva
a observação anterior, com estado e data próprios; ela não vira ausência ou zero.
Medianas de grupos com número par usam a média dos dois valores centrais;
meio centavo é arredondado para longe de zero. Não se misturam exercícios,
etapas financeiras ou classificações distintas em um indicador.

### Reconstrução das contas

```sh
make collect-accounts YEAR=2025
python3 ingest/accounts.py --collect --refresh --year 2025
python3 ingest/accounts.py --year 2025
```

O primeiro comando consulta o cadastro de entes quando ausente, carrega a população
do exercício quando necessário e completa as consultas municipais ausentes em cache.
A atualização forçada refaz consultas; a reconstrução sem `--collect` não acessa a rede. Caches
municipais são gravados atomicamente, permitindo retomada, e ficam em
`data/raw/siconfi/accounts-2025/`. O snapshot final é independente do banco SQLite.
Falhas preservam observações úteis anteriores com indicação de fotografia antiga;
consulta indisponível deve ser tentada novamente na próxima coleta.

As consultas completas de São Paulo/SP e Serra da Saudade/MG foram verificadas na
API: 3.197 e 814 linhas, respectivamente, ambas sem página seguinte. O extrato
registra DCA homologada de 2025 para São Paulo em 30/4/2026 e Serra da Saudade em
5/5/2026. O código SICONFI 53 tem a declaração própria do Governo do Distrito
Federal; não é uma substituição para o código IBGE de Brasília.


### Importação nacional do FINBRA

Os três CSVs de 2025 foram baixados manualmente na consulta pública do FINBRA,
com escopo **Municípios** e sem limitar a data de homologação: receitas (I-C),
despesas orçamentárias (I-D) e despesas por função (I-E). O importador usa leitura
em streaming, codificação Windows-1252, separador ponto e vírgula e valida
exercício, escopo, anexo, cabeçalho e oito campos por linha. Aspas internas da
publicação são toleradas sem dispensar a validação do layout. Identificadores
recebem apenas a remoção do prefixo oficial `siconfi-cor_` para corresponder às
contas da API. Em I-E, o código repetido `TotalDespesas` exige também o nome exato
da função; não se somam linhas nem se confunde o total com saúde ou educação.

```sh
python3 -m ingest.finbra --year 2025
python3 -m ingest.finbra --year 2025 --install-missing
python3 ingest/accounts.py --collect --year 2025
python3 ingest/accounts.py --year 2025
```

Os arquivos de entrada padrão são `data/raw/finbra.csv`,
`data/raw/finbra-expenses.csv` e `data/raw/finbra-functions.csv`.
O estágio `data/raw/siconfi/finbra-2025/` guarda a projeção municipal e um manifesto
com hashes SHA-256 e contagens dos arquivos. O horário do arquivo local registra
a obtenção local; os CSVs não informam a revisão ou o instante de extração no
Tesouro. Não se atribui uma divergência a uma retificação sem essa evidência.

A instalação preenche caches ausentes, preserva os valores já consultados na API
quando coincidem e registra divergências em auditoria local. Valor numérico que
diverge entre as fontes fica ausente; conflito entre o CSV e o extrato de entrega
não recebe o rótulo de não entrega. A consulta posterior à API cobre os municípios
sem linhas nos CSVs. Os arquivos originais, caches e auditoria ficam fora do Git.

Na auditoria de 7/10/2026, os anexos continham 712.113 linhas (I-C), 962.401
(I-D) e 1.105.409 (I-E), sem linhas com número incorreto de campos. Cada seleção
produziu no máximo uma observação por cidade. O somatório de primeiro nível das
funções coincidiu com o agregado “Despesas Exceto Intraorçamentárias” em todas
as 5.499 cidades do anexo I-E, confirmando o escopo desse detalhamento.

Três divergências foram confirmadas em nova consulta à API:

- **Curaçá/BA (2909901):** receita bruta de R$ 200.154.508,19 na API e
  R$ 215.303.277,58 no CSV. Somente a receita foi ocultada e excluída da mediana;
  os quatro indicadores de despesa coincidem entre as fontes.
- **Mato Grosso/PB (2509370)** e **São João do Caiuá/PR (4124905):** os CSVs têm
  valores, mas a API não retorna DCA e o extrato não confirma entrega. A tela
  informa o conflito, com indicadores ausentes, sem afirmar que não entregaram.

O relatório local preserva os registros anteriores à conciliação. Uma nova
importação não substitui indicadores ausentes por valores escolhidos de outra
fonte automaticamente. Para resolver os conflitos, é preciso nova evidência
oficial compatível entre os canais; a data do CSV não explica sua causa.


### Cobertura local concluída em 7/10/2026

| Recorte | Quantidade |
| --- | ---: |
| Localidades no catálogo | 5.571 |
| Municípios aplicáveis com consulta completa ou arquivos nacionais conferidos | 5.569 |
| Municípios com os cinco indicadores disponíveis | 5.494 |
| Municípios com valores parciais ou divergências explícitas | 6 |
| Municípios com não entrega confirmada no extrato | 69 |
| Municípios sem consulta concluída | 0 |
| Localidades fora da DCA municipal (Brasília e Fernando de Noronha) | 2 |
| Populações do exercício de 2025 disponíveis | 5.571 |

O estágio FINBRA tem 5.499 municípios, dos quais 5.497 têm os cinco indicadores
selecionados. Ele completou 1.181 caches ausentes; os demais vieram da API.
A cobertura nacional foi confirmada e as medianas foram liberadas.
Os seis casos parciais são Curaçá/BA, Mato Grosso/PB e São João do Caiuá/PR
(divergências acima), Peabiru/PR (saúde e educação sem valor válido),
Alvorada do Sul/PR (receita sem valor válido) e Volta Redonda/RJ (declaração
registrada, mas nenhum dos cinco indicadores válido na consulta).
Valores parciais só entram no indicador para o qual há valor válido e único.
