# Placar mais amplo — metodologia e piloto

Implementação local em 9/10/2026, na branch `codex/broader-voting-scoreboard`.
Este documento registra a metodologia, a conferência de fontes e o catálogo
paginado de 2026. Integração à `main` e publicação no servidor são etapas separadas.

## Pergunta do cidadão e recorte

“O que meu deputado votou, o que estava sendo decidido e o que significa o voto?”

A proposta de v1 é cobrir **votações nominais abertas do Plenário da Câmara sobre
o texto principal de PL, PLP e PEC**, desde 1º/2/2023. A primeira conferência usa
2026. Entram aprovações e não aprovações, com a mesma regra, sem seleção por
partido, autor, tema, placar apertado ou repercussão.

Substitutivos e subemendas substitutivas podem ser a versão integral decidida.
Os dois turnos de uma PEC são decisões distintas, com IDs e textos próprios.
Urgência, retirada de pauta, admissibilidade e outros procedimentos ficam
separados; emendas e destaques também. Redação final é outra etapa, não um
sinônimo de aprovação do mérito. MPV, PLV, PDL e PRC ficam fora deste primeiro
recorte; essa limitação deve aparecer na página de cobertura.

A interface mantém “O que é o Placar” sempre visível, com a quantidade de votações
conferidas uma a uma e o período consultado. “Como montamos este Placar” fica
recolhido e explica os registros de várias etapas e matérias, os critérios,
as exclusões, pendências e lacunas. O inventário não é só de votações nominais,
e a seleção não classifica as decisões por importância. Não chamar os itens de “decisões finais”:
uma votação do texto principal pode ser uma etapa da tramitação e não comprova
que o projeto virou lei. A quantidade do Placar não mede toda a produção da Câmara.

## O que a fonte permite afirmar

A [documentação da Câmara](https://dadosabertos.camara.leg.br/howtouse/2020-02-07-dados-votacoes.html)
adverte que a proposição afetada pode ser diferente do objeto efetivamente
votado. `objetosPossiveis` não é uma lista de objetos todos votados; nem a última
apresentação de proposição comprova qual versão foi decidida.

Cada candidato precisa de conferência do registro do resultado, do texto
efetivamente submetido e do relatório nominal. Uma ementa do projeto original
não comprova o conteúdo do substitutivo. Casos sem identificação segura ficam
pendentes, com motivo, sem um resumo que atribua efeitos ao voto.

A [lista oficial](https://dadosabertos.camara.leg.br/api/v2/orgaos/180/votacoes)
é consultada por **data de ocorrência**. A data de registro permanece separada.
O campo `aprovacao=0` significa não aprovação; para dizer “rejeitado” é preciso
conferir o resultado, pois também pode haver quórum insuficiente. Campo ausente
não significa rejeição, voto “não”, abstenção ou zero.

O método só fica identificado automaticamente quando o texto o declara de forma
explícita. Placar e linhas individuais, isoladamente, não comprovam o método
nominal: a fonte também tem manifestações individuais em decisões simbólicas.
Um relatório nominal oficial pode resolver essa pendência na revisão humana.

## Levantamento reproduzível

```sh
make collect-vote-inventory YEAR=2026 THROUGH=2026-10-09
# Reconstrução sem rede, com os mesmos limites e caches:
python3 -m ingest.chamber_vote_inventory --year 2026 --through 2026-10-09
```

`ingest/chamber_vote_inventory.py` segue todas as páginas do órgão Plenário
(180), valida datas e IDs e recusa saltos, ciclos e links fora do endpoint
oficial. Duplicatas idênticas são contadas uma vez; conflitos interrompem a lista.
Falha na lista preserva o relatório anterior, sem declarar uma lista parcial
como completa.

Respostas originais, URL, data de consulta e checksum ficam em
`data/raw/chamber-vote-inventory/<início>_<fim>/`. O relatório JSON e a tabela
Markdown ficam em `data/reviews/chamber-vote-inventory-<fim>.*`, fora do Git.
Nada é importado para o SQLite ou para os snapshots que o site usa.

`--start` muda o primeiro dia (por exemplo, `2023-02-01`, início do mandato);
sem `--through`, anos anteriores terminam em 31/12. `--audit-omissions`
(`OMISSIONS=1` no `make`) cruza a lista com os eventos do Plenário, as votações
de cada evento, as pautas das sessões deliberativas e as votações de cada
proposição em pauta ou afetada. O resultado fica em `omissionAudit`: votações
ausentes da lista, registros sem evento vinculado, sessões deliberativas sem
votação listada e falhas de consulta. Cache ausente torna a conferência
incompleta, não a lista. Todas as consultas vêm da mesma API: concordância
reduz o risco de omissão, mas não prova cobertura completa.

A regra `chamber-vote-inventory-v1` faz uma triagem conservadora da descrição:
texto principal, emenda/destaque, procedimento, redação final ou desconhecido.
**Candidato é provisório, não elegível para publicação.** Proposições afetadas
servem para conferir o recorte; um resultado vago continua desconhecido.

A amostra tem até 40 detalhes e 10 consultas de votos individuais. Prioriza
candidatos com placar explícito, dos mais recentes aos mais antigos; depois,
os demais candidatos. Esses limites escolhem a conferência, não o catálogo
final. `--detail-limit` e `--participant-limit` permitem ampliar a amostra.
Contagens não publicadas continuam ausentes, inclusive abstenções.

Para incluir descrições desconhecidas na conferência de detalhes, use
`--audit-unknown` e ajuste `--detail-limit`. A opção não publica registros nem
transforma descrições genéricas em votos do texto principal. A revisão adicional
de 9/10 usa a regra `chamber-vote-inventory-v2`: requerimentos e recursos
explicitamente nomeados são procedimentos; resultados genéricos de manutenção,
supressão ou empate só viram destaques quando a abertura identifica o DTQ.
Preferência entre textos continua sendo procedimento. A ressalva “com exceção
dos dispositivos rejeitados” não oculta a aprovação de um substitutivo inteiro.
A regra `chamber-vote-inventory-v3` (10/10/2026) corrige um erro da v2: o nome
por extenso “Proposta de Emenda à Constituição” contém “emenda” e fazia turnos
de PEC parecerem votações de emenda. A v3 também trata “aprovada a PEC ... na forma
da Emenda Aglutinativa” como texto principal; uma emenda aglutinativa votada
isoladamente continua sendo emenda. Com a v3, oito turnos de PEC de 2026 e cinco
de 2023 entram como candidatos.

**Lição.** Regra por palavra-chave falha em silêncio: o registro não some, muda de
categoria, e a revisão só olha candidatos. O catálogo de 2026 chegou a ser dado como
revisado com zero PECs. Por isso o inventário grava `typeGuard`, com candidatos por
tipo (PL, PLP e PEC), turnos de PEC fora dos candidatos e aprovações ou rejeições
de texto inteiro (projeto, substitutivo, subemenda substitutiva, PEC, emenda
aglutinativa substitutiva) classificadas como emenda ou desconhecido; o relatório
Markdown destaca cada caso. Em 2024 o alerta apontou mais dois: o 1º turno da PEC
31/2007 na forma de emenda aglutinativa substitutiva e o substitutivo do Senado ao
PLP 175/2024, cuja ressalva “com exceção de …” mencionava uma supressão. A v3
passou a ignorar essas ressalvas em substitutivos do Senado aprovados. Antes de fechar um ano, todo alerta precisa de explicação com
fonte; ao mudar uma regra, rode-a contra os inventários existentes e liste cada
registro que muda de candidato.

Nos votos individuais, todas as páginas são lidas. IDs duplicados com escolhas
conflitantes são recusados; Sim, Não e Abstenção são comparados separadamente
com o placar observado. Presidência (“Artigo 17”) e obstrução permanecem
distintas; quantidade de linhas não é automaticamente o total de votos.

## Resultado do piloto de 9/10/2026

Consulta de 1º/1 a 9/10/2026: **1.339 registros, em 14 páginas**, com datas de
ocorrência observadas entre 2/2 e 3/9. “Lista completa” significa que toda a
paginação retornada pela API foi lida; não garante que a fonte tenha registrado
todas as decisões que efetivamente ocorreram.

| Triagem provisória | Registros |
| --- | ---: |
| Texto principal, incluindo tipos fora da v1 | 207 |
| Emenda ou destaque | 78 |
| Procedimento | 705 |
| Redação final | 192 |
| Descrição ainda sem classificação segura | 157 |
| Total | 1.339 |

Há **162 candidatos provisórios ao recorte PL/PLP/PEC**, 19 com placar explícito
na descrição. Isso não equivale a 162 votações nominais elegíveis. Foram
conferidos 40 detalhes e 10 conjuntos de votos individuais, sem falhas de fonte;
os valores publicados de Sim, Não e, quando informado, Abstenção bateram nos
10 casos. Naquela triagem, os candidatos ainda precisavam de confirmação de
método antes de publicação, pois o texto da API não a resolveu automaticamente.

Um caso ilustra por que a conferência precisa preservar cada estado: no PLP 74,
o resultado tem 395 votos, mas a lista individual tem 396 pessoas, incluindo
uma presidência (“Artigo 17”). Essa linha adicional não é um voto extra.

Casos reais incorporados às regras e testes: “Rejeitadas as Emendas ao
Substitutivo” é decisão sobre emendas; mudança do regime por um requerimento
apensado é procedimento; “ressalvado o destaque” é uma ressalva do texto
principal, não um placar do destaque. Texto mantido sem identificação do trecho
fica desconhecido. As palavras do registro precisam identificar a decisão,
não apenas mencionar o projeto a que ela se relaciona.

## Exemplos da conferência

Estes três exemplos partem de itens já presentes no Placar, para conferir a
continuidade das fontes. Não definem o critério de escolha do catálogo novo.
Os relatórios oficiais identificam votação nominal eletrônica nos três casos.
O resultado abaixo é o daquela decisão na Câmara; não afirma a situação legal
atual da proposição.

### PLP 74/2026 · 3/9/2026

**Título:** Regras para benefícios tributários e despesas de 2026.

**O que foi decidido:** a Câmara aprovou uma subemenda substitutiva adotada pelo
relator da Comissão de Finanças e Tributação. A versão decidida substituiu os
textos anteriores; este placar não é uma votação do projeto original.

**Sim:** aprovar essa subemenda substitutiva. **Não:** rejeitar essa versão.
**Resultado:** 346 Sim, 46 Não e 3 abstenções; aprovado.

[Relatório nominal](https://www.camara.leg.br/internet/votacao/mostraVotacao.asp?codCasa=1&ideVotacao=13931&indTipoSessao=E&indTipoSessaoLegislativa=O&numLegislatura=57&numSessao=160&numSessaoLegislativa=4&tipo=uf),
[registro da sessão](https://www.camara.leg.br/internet/ordemdodia/integras/3177907.htm)
e [detalhe da API](https://dadosabertos.camara.leg.br/api/v2/votacoes/2611313-31).
Explicações de efeitos específicos exigem conferir o texto desta versão.

### PLP 114/2026 · 12/8/2026

**Título:** Substitutivo ao projeto sobre tributos de combustíveis.

**O que foi decidido:** a Câmara aprovou o substitutivo reformulado da relatora,
ressalvado um destaque. Esse placar diz respeito ao substitutivo; emendas e o
destaque têm decisões próprias.

**Sim:** aprovar esse substitutivo. **Não:** rejeitar essa versão.
**Resultado:** 318 Sim, 113 Não e 1 abstenção; aprovado.

[Relatório nominal](https://www.camara.leg.br/Internet/votacao/mostraVotacao.asp?codCasa=1&ideVotacao=13872&indTipoSessao=E&indTipoSessaoLegislativa=O&numLegislatura=57&numSessao=151&numSessaoLegislativa=4&tipo=partido),
[registro da sessão](https://www.camara.leg.br/internet/ordemdodia/integras/3171603.htm)
e [ficha e tramitação](https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=2618177).

### PLP 41/2026 · 7/7/2026

**Título:** Substitutivo ao projeto de enfrentamento da violência contra mulheres.

**O que foi decidido:** a Câmara aprovou o substitutivo da relatora da Comissão
de Defesa dos Direitos da Mulher. A ementa descreve um sistema nacional de
enfrentamento da violência contra meninas e mulheres e destinação de recursos.

**Sim:** aprovar esse substitutivo. **Não:** rejeitar essa versão.
**Resultado:** 470 Sim e 1 Não; aprovado. Abstenções não são completadas a partir
da ausência de informação no resumo.

[Relatório nominal](https://www.camara.leg.br/internet/votacao/mostraVotacao.asp?codCasa=1&ideVotacao=13830&indTipoSessao=E&indTipoSessaoLegislativa=O&numLegislatura=57&numSessao=136&numSessaoLegislativa=4&tipo=uf)
e [ficha e tramitação](https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=2606313).
O rascunho não repete a regra de 10% ligada ao Propag do cartão antigo: esse
efeito precisa ser conferido no substitutivo antes de reaproveitar o resumo.

## Primeiro lote do catálogo local de 2026

Os 19 candidatos com placar explícito passaram por conferência do relatório
nominal, da data, do resultado e da versão identificada na decisão oficial.
Os votos individuais são conciliados com Sim, Não, Abstenção quando publicada
e Total. Presidência e obstrução ficam separadas; pessoas sem linha na fonte
não recebem um voto inventado.

A revisão fica em `data/reviews/chamber-vote-reviews-2026-10-09.json`, fora do
Git, com ID, status, data da revisão, título, resumo, significados de Sim/Não,
links oficiais e evidências do método e da versão. Status `pending` exige um
motivo e não publica o item. Status `excluded` exige motivo, data, fonte oficial
e evidência; também não publica o item. A cobertura separa publicadas, excluídas
e pendentes, incluindo candidatos ainda não revisados entre as pendências.
`reviewedCount` conta candidatos com revisão registrada, inclusive pendências;
não é uma quantidade de decisões nominais. O novo campo `excludedCount` é
opcional para manter a leitura dos snapshots anteriores, sem tratar sua ausência
como uma contagem zero. `missingTextCount`, `missingAbstentionCount` e
`missingThemeCount` também são contagens opcionais, calculadas sobre os resumos
publicados e usadas na lista de limites. Cada contagem fica entre zero e
`publishedCount`; ausência do campo não vira zero. Confirmar o objeto pelo relatório e pela sessão
não autoriza atribuir efeitos específicos de uma ementa anterior. Quando não
há link seguro para o texto daquela versão, `sources.text` fica ausente como
valor (`null`); a página mantém o relatório e o registro da decisão.

```sh
make collect-votes THROUGH=2026-10-09
# Reconstrução offline com as revisões e caches locais:
python3 -m ingest.chamber_votes --through 2026-10-09
```

`--reviews <arquivo>` aceita outro arquivo local de revisão. O coletor valida
links oficiais, confirma o marcador nominal no relatório, segue todas as
páginas dos votos individuais e preserva os múltiplos
[temas oficiais da proposição de referência](https://dadosabertos.camara.leg.br/swagger/api.html#proposicoes).
Uma proposição sem temas continua sem temas. Falhas na coleta ou conciliação
interrompem a geração e preservam o catálogo anterior. Os originais ficam no
cache do inventário com URL, data de consulta e checksum.

O índice `data/snapshots/chamber-votes.json` contém somente resumos e cobertura;
cada lista nominal fica em `data/snapshots/chamber-vote-details/<geração>/<id>.json`.
Uma geração é identificada pelo checksum do conjunto de detalhes. Ela é preparada
integralmente antes de trocar o índice de forma atômica; falhas não misturam
resumos antigos com detalhes novos. Gerações anteriores são preservadas.
`GET /api/c/votes` oferece busca, tipo, tema e paginação (12 itens por página,
limite de 24). `GET /api/c/votes/<id>` carrega a decisão e seus votos individuais.
Nenhuma dessas rotas depende do SQLite. Falha ou ausência do detalhe não elimina
o resumo: a API indica que a lista individual está indisponível.

O Placar usa esse catálogo ao entrar na tela, com filtros, cobertura, fontes,
significados de Sim/Não e endereço `/placar/<id>`. A home, as fichas, os partidos
e as comparações mantêm as quatro seleções originais e seus contratos em `DATA`.
Num clone sem snapshots, o Placar informa a indisponibilidade e mostra essas
seleções. Uma busca sem resultados num catálogo disponível mostra lista vazia.

Esta entrega cobre **19 decisões conferidas**, não todo o ano nem todo o mandato.
São **7.859 registros individuais**, incluindo presidência e obstrução quando
presentes; não é um total de votos de mérito. Quatro decisões não têm link seguro
para o texto exato, nove não publicam a contagem de abstenções na descrição da
API e uma não tem tema oficial. Essas lacunas permanecem explícitas, sem zeros
ou links inferidos.
Nesse primeiro lote, os outros **143 candidatos provisórios** aguardavam revisão; podiam incluir decisões
simbólicas e itens que serão excluídos após conferir o método e o objeto.
O fato de as 19 decisões deste lote terem sido aprovadas é uma observação das
fontes, não um critério de inclusão. A regra também admite não aprovações.

## Conferência de método e objeto na continuação

A revisão adicional consulta o [portal de votação nominal e simbólica](https://www.camara.leg.br/presenca-comissoes/votacao-portal?reuniao=82956)
de cada sessão e, quando necessário, as [notas taquigráficas oficiais](https://escriba.camara.leg.br/escriba-servicosweb/html/82956).
A opção do portal precisa corresponder à proposição, ao objeto e à sessão;
um destaque nominal não torna nominal a votação adjacente do substitutivo.
A ausência de opção ou relatório não comprova votação simbólica e mantém a
pendência quando nenhuma outra fonte resolve o método.

Nas notas, a chamada para os favoráveis permanecerem como se acham seguida da
proclamação do resultado identifica o processo simbólico descrito no
[art. 185 do Regimento Interno](https://www2.camara.leg.br/legin/fed/rescad/1989/resolucaodacamaradosdeputados-17-21-setembro-1989-320110-normaatualizada-pl.html).
É preciso conferir o trecho do objeto correto e eventual verificação nominal
posterior. Por exemplo, na sessão de 2/9/2026 o presidente iniciou a chamada
para registrar votos do substitutivo ao PL 3.904/2023, mas em seguida mudou
explicitamente para votação simbólica. O registro dessa decisão não entra no
catálogo nominal.

Os 157 registros inicialmente desconhecidos receberam revisão individual:
105 eram procedimentos, 51 eram destaques ou uma subemenda ao substitutivo,
e um era a votação simbólica do substitutivo do Senado ao PL 3.780/2023.
Esse último passa a candidato provisório na regra v2 e é excluído pelo método
confirmado nas notas; a votação nominal do DTQ 7 permanece separada.
Os relatórios locais preservam a coorte inicial para que os números de etapas
diferentes não sejam confundidos.

Uma decisão adicional foi confirmada como nominal eletrônica: a subemenda
substitutiva ao PL 1.625/2026, de 20/5/2026. O
[relatório nominal](https://www.camara.leg.br/internet/votacao/mostraVotacao.asp?ideVotacao=13735)
publica 268 Sim, 113 Não e total de 381. A descrição dos Dados Abertos não traz
o placar e a consulta individual devolve uma lista vazia. Isso não foi tratado
como zero votos: os 381 registros foram lidos do relatório e ligados, sem
aproximação de nomes, a IDs únicos na lista oficial de deputados da mesma data,
usando nome e UF. Abstenções não publicadas continuam como `null`.

Esse caminho exige revisão explícita com `tallySource: "rollCall"`,
`participantsSource: "rollCall"` e `reportObject`. O parser confere método,
proposição, objeto, data, horário final, placar e cada registro; identidade
ausente ou ambígua interrompe a geração. Uma lista parcial ou uma consulta
que falhou não é substituída silenciosamente. Os caches preservam também a
resposta vazia da API e a lista de identidade; não alteram o conteúdo original
da fonte. O novo campo opcional `dataNotes` informa essa origem ao abrir a
decisão, mantendo a compatibilidade com os resumos anteriores.

## Resultado consolidado de 9/10/2026

Os 143 candidatos restantes do primeiro lote foram revisados: 142 excluídos e
uma nova decisão nominal confirmada. Somados aos 157 registros inicialmente
desconhecidos, são 300 revisões adicionais, com fontes e motivos locais.
A regra v2 retira quatro requerimentos de dispensa de interstício da lista de
candidatos e acrescenta provisoriamente o substitutivo do Senado ao PL 3.780,
depois excluído como simbólico. Por isso o denominador atualizado é **159**,
em vez dos 162 da triagem inicial.

| Triagem v2 após os detalhes | Registros |
| --- | ---: |
| Texto principal, incluindo tipos fora da v1 | 204 |
| Emenda ou destaque | 129 |
| Procedimento | 814 |
| Redação final | 192 |
| Descrição ainda sem classificação segura | 0 |
| Total retornado pela lista | 1.339 |

Dos 159 candidatos, **20 decisões nominais estavam no catálogo local**, 139 foram
excluídas com fonte e nenhuma seguia pendente de método ou objeto. O catálogo tinha
**8.240 registros individuais**, incluindo presidência e obstrução quando
presentes. Isso não é uma quantidade de votos de mérito nem prova de completude
dos registros oficiais do ano.

**Correção de 10/10/2026.** A regra v2 classificava turnos de PEC escritos por
extenso como emendas, e o catálogo não tinha nenhuma PEC. Com a v3, oito turnos
de PEC de 2026 entraram como candidatos (167 no total). Os oito são nominais
pelos relatórios oficiais e foram publicados: PEC 18/2025, PEC 383/2017,
PEC 221/2019 e PEC 5/2023, em dois turnos cada. O catálogo passou a ter **28
decisões**, 139 exclusões, nenhuma pendência e 12.087 registros individuais. Nos
quatro segundos turnos, não há documento oficial do texto submetido separado da
redação final; o link do texto fica ausente e entra na contagem de lacunas
(4 sem texto, 15 sem abstenções publicadas, 1 sem tema).

Três links exatos antes pendentes foram recuperados: o substitutivo ao PLP 80/2026
e a subemenda ao PLP 337/2017 estão anexados a pareceres; o PLP 262/2019 teve o
projeto principal votado antes de sua emenda separada. Seus resumos agora usam
conteúdo verificado dessas versões.

A conferência seguinte também resolveu o SBT 1 do PL 4.133/2023. A
[ficha do SBT 1, ID 2633548](https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=2633548)
e sua API vinculam explicitamente o objeto ao [PDF codteor 3148936](https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=3148936#page=11),
com o substitutivo completo nas páginas 11–28. As [notas da sessão 120, evento 82555](https://escriba.camara.leg.br/escriba-servicosweb/html/82555)
identificam esse substitutivo como objeto da votação e confirmam o resultado
308 Sim, 129 Não e uma abstenção. O registro do parecer às 17:26 e do SBT às
18:15 não demonstra versões diferentes: os registros oficiais ligam ambos ao
mesmo arquivo antes da votação das 18:37–18:53.

A auditoria anterior errou ao tratar o artigo sobre defesa do mercado interno
como novo na redação final: ele já está na página 22 do substitutivo, conferida
visualmente. A redação final tem diferenças e não foi usada como texto votado;
o vínculo seguro é com o SBT registrado. As fontes, a correção e os insumos
anteriores ficam em `data/reviews/pl4133-exact-text-followup/`, fora do Git.

Há **zero decisões sem texto exato ligado**, **dez sem contagem publicada de
abstenções** nas fontes do placar e **uma sem tema oficial**.

A reprodução offline da triagem usa 215 detalhes selecionados pelas regras
atuais e 19 consultas de votos individuais, sem falhas; os caches e as auditorias
guardam também os detalhes dos 319 registros das coortes originalmente revistas.
O vigésimo conjunto individual é o relatório nominal do PL 1.625, com a resposta
vazia da API preservada e a lista oficial de identidade em seis páginas.

```sh
python3 -m ingest.chamber_vote_inventory --year 2026 --through 2026-10-09 \
  --detail-limit 400 --participant-limit 19 --audit-unknown
python3 -m ingest.chamber_votes --through 2026-10-09
```

As auditorias das coortes iniciais ficam em `data/reviews/scoreboard-candidate-audit-{recent,older}.json`
e `data/reviews/scoreboard-unknown-audit-2026-10-09.json`; a revisão consolidada
continua em `chamber-vote-reviews-2026-10-09.json`. Os insumos do primeiro lote
foram preservados em `data/reviews/scoreboard-audit-initial-2026-10-09/`.
Todos esses arquivos, fontes e snapshots continuam fora do Git.

A conferência de omissões de 2026 (164 eventos, 70 deliberativos, 890 votações
vinculadas e 786 proposições) não encontrou votação ausente da lista nem falha
de consulta. As seis sessões deliberativas sem votação listada foram conferidas
nas pautas e tramitações, sem decisão de mérito.

## Proposição votada diferente da referência da API

Em alguns registros a API liga a votação a outra proposição (por exemplo, a
principal de um apensado) ou mostra a numeração atual de uma proposição
renumerada. A revisão declara então `votedProposition: {"id", "label"}`, com o
número do relatório nominal. O coletor exige que o relatório traga esse número
na mesma data e, quando o ID difere, que a ficha oficial o confirme. O Placar
mostra o número do relatório, liga a ficha da proposição votada e preserva o
registro da API em `sources.vote` e, quando o ID difere, em
`sources.referenceProposition`; uma nota explica a diferença. Temas vêm da
proposição votada.

O leitor do relatório aceita sessões e votações que terminam após a meia-noite;
a data da sessão é a da abertura. Quando o relatório é a origem do placar ou dos
votos, o registro da API pode vir até cinco minutos após o encerramento.

## Catálogo de vários anos

Cada ano tem inventário e revisão próprios, nomeados pela data final. Para
juntar anos contíguos no mesmo índice, repita `--through`:

```sh
python3 -m ingest.chamber_votes --through 2023-12-31 --through 2024-12-31 \
  --through 2025-12-31 --through 2026-10-09
make collect-votes THROUGH="2023-12-31 2024-12-31 2025-12-31 2026-10-09"
```

Os períodos precisam ser contíguos (31/12 seguido de 1º/1); o primeiro pode
começar em 1º/2/2023. IDs repetidos entre anos são recusados. A cobertura soma
as contagens de cada ano, o período vai do primeiro início ao último fim, e o
índice mantém `schemaVersion: 1`. `--reviews` só vale para um único ano.

## Levantamento de 2023

Inventário de 1º/2 a 31/12/2023 com a regra v3 e `--audit-omissions`:

| Observação | Quantidade |
| --- | ---: |
| Registros retornados pela API | 1.049, em 11 páginas |
| Candidatos | 159 |
| Simbólicos pelo portal da sessão | 96 |
| Simbólicos pelas notas taquigráficas | 22 |
| Nominais confirmados por relatório oficial | 41 |
| Pendentes | 0 |
| Registros individuais nas 41 decisões | 17.120 |
| Sem link seguro ao texto exato | 3 |
| Sem contagem publicada de abstenções | 10 |
| Sem tema oficial | 0 |

A conferência de omissões cruzou 285 eventos (113 deliberativos), 975 votações
vinculadas e 625 proposições, sem votação ausente da lista nem falha. As 15 sessões
deliberativas sem votação listada não tiveram decisão de mérito (eleição para o
TCU, matérias não apreciadas, adiamentos ou pauta vazia). Os 37 registros sem
classificação são requerimentos, eleições, preferência, pareceres de comissão
mista e uma emenda.

Em nove decisões, a API liga a votação a outra proposição ou à numeração atual:
o Placar usa `votedProposition` com o número do relatório. Os três textos
ausentes são o 2º turno de julho e os dois turnos de dezembro da PEC 45/2019,
sem documento do texto submetido separado da redação final. Uma descrição da API
soma obstruções ao total (PL 3.954/2023); o Placar usa o total do relatório.

O índice conjunto exige anos contíguos: 2023 só entra no site junto com 2024 e
2025. A revisão de 2023 e as evidências ficam em
`data/reviews/chamber-vote-reviews-2023-12-31.json` e
`data/reviews/scoreboard-audit-2023/`, fora do Git.

## Levantamento de 2024

| Observação | Quantidade |
| --- | ---: |
| Registros retornados pela API | 2.128, em 22 páginas |
| Candidatos (PL 156, PLP 17, PEC 6) | 179 |
| Simbólicos pelo portal da sessão | 113 |
| Simbólicos pelas notas taquigráficas | 22 |
| Parte do texto (bloco rejeitado do substitutivo do Senado) | 1 |
| Nominais confirmados por relatório oficial | 43 |
| Pendentes | 0 |
| Registros individuais nas 43 decisões | 18.194 |
| Sem link seguro ao texto exato (2º turnos de PEC) | 3 |
| Sem contagem publicada de abstenções | 18 |
| Sem tema oficial | 0 |

A conferência de omissões cruzou 253 eventos (86 deliberativos), 927 votações
vinculadas e 721 proposições, sem votação ausente nem falha. As quatro sessões
deliberativas sem votação listada não tiveram decisão de mérito.

Retornos do Senado votados em blocos seguem o precedente do PL 3.780: o bloco com
parecer pela aprovação decide a versão do Senado e entra como texto principal, com
a exceção descrita; o bloco com parecer pela rejeição é parte do texto e fica fora.
Duas votações começaram no painel e foram convertidas em simbólicas pelo presidente
(PL 3.817/2024; o PL 81/2024 teve só preferência nominal); a API não traz votos
individuais nelas. O PL 4.685/2012 aparece nas notas com o número do Senado
(PL 6.606/2019). Evidências em `data/reviews/scoreboard-audit-2024/`, fora do Git.

## Levantamento de 2025

| Observação | Quantidade |
| --- | ---: |
| Registros retornados pela API | 2.017, em 21 páginas |
| Candidatos (PL 167, PLP 21, PEC 12) | 200 |
| Simbólicos pelo portal da sessão | 84 |
| Simbólicos pelas notas taquigráficas | 40 |
| Parte do texto (bloco rejeitado do substitutivo do Senado) | 1 |
| Nominais confirmados por relatório oficial | 75 (um com resultado rejeitado) |
| Pendentes | 0 |
| Registros individuais nas 75 decisões | 31.452 |
| Sem link seguro ao texto exato | 9 |
| Sem contagem publicada de abstenções | 40 |
| Sem tema oficial | 0 |

A conferência de omissões cruzou 310 eventos (121 deliberativos), 1.208 votações
vinculadas e 838 proposições, sem votação ausente nem falha; o alerta por tipo não
apontou registros. Em 2025 o portal da sessão deixou de listar muitas votações, e
as notas taquigráficas decidiram 40 casos (todos simbólicos, com trecho conferido).

Relatórios de votação unânime não publicam a linha “Não”; o leitor deriva zero
apenas quando o “Total da Votação” é igual ao número de Sim. Quando o placar vem
do relatório e os votos individuais vêm da API, a conciliação nominal confirma o
vínculo e o limite de cinco minutos do horário de registro deixa de ser exigido.
Sem link de texto ficaram os 2º turnos de PEC, os dois turnos das PECs 39/2022 e
169/2019 (parecer da comissão não conferido), o substitutivo ao PL 2.664/2003 (sem
documento) e a subemenda ao PL 1.087/2025, com duas versões registradas na sessão.

Votações de **emendas do Senado** (não de substitutivo), como as do PL 2.159/2021,
continuam fora do recorte v1, como nos anos anteriores. Decisão de 10/10/2026: a
inclusão será uma expansão separada, com a mesma regra aplicada aos quatro anos;
a relevância de um caso isolado não justifica exceção.

## Índice conjunto de 2023 a 2026

Gerado em 10/10/2026 com quatro `--through`: 187 decisões, 705 candidatos, 518
exclusões, 0 pendências, 6.533 registros da API; período de 1º/2/2023 a 9/10/2026.
Lacunas: 19 sem texto, 83 sem abstenções, 1 sem tema. O índice anterior, só de
2026, ficou em `data/reviews/scoreboard-audit-2025/chamber-votes.index-2026-only.json`.

## Decisões sobre trechos (piloto de 10/10/2026)

Pergunta: o que o deputado decidiu sobre partes do projeto, além do texto principal?
Um deputado pode apoiar o projeto e votar contra um trecho; a votação do texto principal
não mostra isso.

Regra do piloto: os cinco projetos mais recentes do Placar com destaque ou emenda votados
nominalmente, e **todas** as votações nominais de destaque ou emenda desses projetos, sem
escolher pelo placar. Resultado: 8 decisões em PLP 114/2026, PEC 5/2023 (1º turno),
PL 1.625/2026, PEC 383/2017 (2º turno) e PLP 77/2026.

Cada revisão fica em `data/reviews/chamber-vote-segment-reviews-<through>.json` (fora do Git)
e traz o trecho em disputa, o significado de Sim e Não, o resultado (`approved`, `rejected`,
`kept` ou `removed`), o objeto exato do relatório nominal e evidência de método, objeto e
texto. A coleta (`ingest/chamber_vote_segments.py`) só publica quando:

- a votação principal da mesma proposição está publicada e é a última antes da decisão, sem outra
  votação principal no meio (destaques podem ficar para outra sessão: no PLP 108/2024, o texto-base
  foi aprovado em 13/8/2024 e os destaques, em 30/10/2024);
- o registro da API existe no inventário, não é anterior à votação principal e tem resultado compatível
  (`aprovacao` 1, 0 ou ausente para votação em separado de trecho);
- o relatório nominal oficial tem a mesma proposição, o objeto revisado e o mesmo placar,
  e a API registrou a decisão até cinco minutos depois do encerramento;
- a lista individual soma o placar.

As decisões ficam penduradas na votação principal (`segments`), com detalhe próprio na mesma
geração. Não entram em `publishedCount`, na concordância entre deputados, na unidade nem nas
comparações de partidos. O conteúdo editorial foi conferido no inteiro teor oficial de cada
destaque (DTQ), emenda (EMP, ERD) e parecer às emendas.

Segundo lote (11/10/2026), mesma regra, cinco projetos seguintes: 20 decisões em PLP 128/2025,
PLP 163/2025, PL 4.278/2025, PLP 108/2024 (agosto/outubro de 2024 e dezembro de 2025) e
PL 4.497/2024 (junho e dezembro de 2025). Total do piloto: 28 decisões em 10 projetos. Nos
substitutivos do Senado (PLP 108/2024 e PL 4.497/2024), votar Sim aprova o dispositivo do Senado
e votar Não o rejeita; vários destaques foram pedidos "para fins de aprovação". Quando a descrição
da API omite os votos Não (Emenda Aglutinativa nº 1 ao PLP 108/2024, 403 × 0), a contagem vem do
relatório nominal, com nota de dados.

Ampliação (11/10/2026): todas as 189 candidatas restantes nos projetos do Placar. A parte mecânica
(votação principal, relatório nominal pela ordem `ideVotacao` e pelo placar, documento oficial do
destaque ou da emenda e extração do texto) foi automatizada; a redação foi feita por agentes em
paralelo com um guia único e conferida pela coleta, decisão a decisão. Resultado: 217 revisões, 193
publicadas e 24 pendentes com motivo (17 sem relatório nominal localizado, 2 com
proposição apensada de outra numeração, 2 com a votação principal em outro ano do catálogo, 1 com
total da API que inclui o voto do presidente, 1 com outra votação principal no meio e 1 sem documento
que explique o efeito do trecho). No mesmo dia (dois turnos de PEC), a ordem dos relatórios nominais
decide a qual votação principal o trecho pertence. Novo tipo: `dispositivos`, para dispositivos do
Senado votados em bloco.

Contagem do catálogo após a ampliação: 193 decisões sobre trechos ligadas a 85 votações do texto
principal, de 74 proposições. Elas aparecem sob 75 IDs de origem porque a PEC 45/2019 tem dois IDs nos
Dados Abertos (259094 e 2196833).

Regras de redação que valem para todas as revisões:

- Resultado: a descrição da API decide ("Mantido" → mantido, "Suprimido" → retirado, "Rejeitada" →
  rejeitada, "Aprovada" → aprovada) e o campo `aprovacao`, quando existe, tem de concordar; sem as
  duas coisas a decisão é recusada.
- Bloco e signatário são informações distintas: quando o relatório nominal atribui o destaque a um
  bloco ("BLOCO PL", "BL. PL, FDR. PT…"), o resumo cita o bloco como consta no relatório e, à parte,
  quem assinou o requerimento, com partido e UF.
- Texto conferido: a evidência registra qual versão foi lida. Quando o substitutivo publicado é imagem,
  vale OCR conferido contra o texto anexo ao parecer, ou o próprio texto anexo ao parecer adotado, com
  o motivo registrado.
- Rótulos de resultado seguem o objeto ("Capítulo mantido", "Alínea mantida", "Inclusão rejeitada" etc.).

Achado: na sessão do PL 1.625/2026, o relatório nominal das 21:56 (ideVotacao 13736) registra
182 × 182 para o mesmo destaque da emenda nº 2, que aparece nos Dados Abertos como
2613731-65, descrito só como “Resultado”. A decisão publicada é a das 22:25 (196 × 200).

Custo medido: localizar o relatório nominal certo (os destaques ficam logo depois da votação
principal na numeração `ideVotacao`) e ler o inteiro teor de cada destaque ou emenda. Antes
de ampliar para as cerca de 216 candidatas nos projetos do Placar, decidir se a frase de
contexto da relatoria (por exemplo, emendas rejeitadas "por não integrarem o acordo") entra
sempre ou só quando o parecer a traz.

## Próxima etapa

Expansão separada para emendas do Senado, nos quatro anos; integrar à `main` e
publicar código e dados em etapa separada. Atualizar 2026 com novas coletas
(`--through` posterior a 9/10) seguindo o mesmo fluxo. A
conferência não autoriza declarar cobertura completa do ano ou do mandato.
