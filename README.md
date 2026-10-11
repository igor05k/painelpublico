# Painel Público

Protótipo para entender, em linguagem simples, gastos, presença e votações de deputados(as) e senadores(as). Alertas indicam registros para conferir, não conclusões de irregularidade.

A área **Minha cidade** reúne a base nacional do IBGE, os resultados eleitorais do TSE, as emendas municipais do Portal da Transparência e as contas anuais do SICONFI, com busca por nome, fontes, períodos e indicação de dados ausentes.

É um projeto pessoal, independente e apartidário, sem vínculo com partidos, políticos ou órgãos públicos. Ele apenas reúne e organiza informações que os próprios órgãos já publicam. Veja o [Aviso legal](LEGAL-NOTICE.md).

## Rodar localmente

Requer **Python 3.10+**. Para os testes de frontend, **Node.js 18+**. A aplicação, o build e os testes não precisam de pacotes Python externos. A coleta opcional de presença do Senado em PDFs requer `pdfplumber`; veja a instalação em [Dados e SQLite](docs/data.md).

```sh
make dev
```

Abra [localhost:8000](http://127.0.0.1:8000/). `make dev` gera `dist/index.html` e inicia a API local. Não faz downloads nem reimporta o banco. Depois de editar o frontend, rode `make build` e recarregue a página; alterações Python exigem reiniciar o servidor.

A base já existente em `data/na-lupa.sqlite3` é preservada. Este repositório publica somente código, testes e documentação: banco, snapshots complementares, downloads e credenciais são locais.

**Em um clone novo**, `make check`, `make build` e `make dev` não dependem de `editorial.json` nem de snapshots privados. `make db-init` prepara um banco vazio; para consultar a base parlamentar completa, obtenha os arquivos normalizados e importe-os conforme [Dados e SQLite](docs/data.md). O build não baixa dados. Presença, votos e perfis são complementos opcionais, coletados manualmente; no servidor, a cota do ano corrente é atualizada todo dia por um timer do systemd.

Sem Make:

```sh
python3 scripts/build.py
python3 -m backend.server --port 8000
```

## Comandos

| Comando | Uso |
|---|---|
| `make dev PORT=8001` | Rodar em outra porta |
| `make build` | Gerar HTML em `dist/` |
| `make check` | Build, sintaxe e testes locais |
| `make db-init` | Criar/atualizar esquema sem apagar dados |
| `make db-check` | Conferir integridade e cobertura numérica |
| `make db-backup` | Backup SQLite consistente e datado |
| `make import` | Importar arquivos locais de `data/imports/` |
| `make collect-legislative YEAR=2026` | Baixar dados da Câmara e do Senado |
| `make collect-profiles` | Coletar manualmente os complementos das fichas; depois rode `make build` |
| `make collect-senate YEAR=2026` | Coletar presença registrada de 2026 e votos/autoria do mandato; depois rode `make build` |
| `make collect-senate-mandate` | Coletar votos nominais e autoria desde fev/2023, sem baixar PDFs de presença |
| `make collect-project-status` | Consultar a situação dos projetos já listados, com fontes e datas; atualização e modo offline em [Dados e SQLite](docs/data.md) |
| `make collect-vote-inventory YEAR=2026` | Levantar votações do Plenário para o Placar; relatório local e metodologia em [Piloto do Placar](docs/voting-scoreboard.md) |
| `make collect-votes THROUGH=2026-10-09` | Gerar o catálogo paginado a partir das revisões locais, com votos individuais separados; [coleta e cobertura](docs/voting-scoreboard.md) |
| `make collect-accounts YEAR=2025` | Coletar contas anuais municipais do SICONFI, com cache e reconstrução offline |
| `make collect-amendments YEAR=2026` | Coletar emendas por município e ano da proposta; valores empenhados e pagos separados |
| `make collect-cities` | Coletar a base nacional de Minha cidade (IBGE e TSE); reconstrução offline em [Dados e SQLite](docs/data.md) |
| `make collect-elections` | Ligar a lista atual às candidaturas de 2026 no TSE; depois rode `make build` |
| `make update-daily` | Atualização diária da cota: coleta, importa em cópia, verifica e publica; no servidor roda por timer ([Publicação](docs/deploy.md)) |
| `make prod` | Rodar como em produção (cache, só localhost) |
| `make deploy` / `make deploy-db` | Publicar código / banco no servidor ([Publicação](docs/deploy.md)) |

## Estrutura

```text
backend/        API Python, consultas e esquema SQLite
frontend/       template HTML, scripts e design system
scripts/        montagem do app
ingest/         coletores oficiais; editorial/ contém complementos manuais da Câmara
data/           snapshots, banco e downloads locais, fora do Git
tests/          testes Python e Node
docs/           arquitetura, dados, visual e próximas etapas
dist/           app gerado, ignorado no Git
```

## Convenções

- [Arquitetura](docs/architecture.md): divisão de responsabilidades e fluxo dos dados.
- [Design system](docs/design-system.md): componentes, temas e bordas neutras.
- [Dados e SQLite](docs/data.md): fontes, limitações, importação e backups.
- [Alertas da cota](docs/alerts.md): regras, prazos, cobertura, simulação e decisões registradas.
- [Contribuição](CONTRIBUTING.md): branches curtas, commits por finalidade e verificações.
- [Próximas etapas](docs/roadmap.md): expansão planejada, separada da cobertura entregue.

O servidor usa `127.0.0.1` por padrão e serve somente o app e a API. O código está em [igor05k/painelpublico](https://github.com/igor05k/painelpublico); publicar código no GitHub não publica o site nem a base. A instalação do servidor e do túnel está descrita em [Publicação](docs/deploy.md). `.env.example` e os arquivos `*.example.*` contêm apenas modelos de configuração.

## Licença

Código sob a [licença MIT](LICENSE). Os dados exibidos pertencem às fontes públicas indicadas em [Dados e SQLite](docs/data.md); veja também o [Aviso legal](LEGAL-NOTICE.md).
