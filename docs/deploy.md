# Publicação

O site é o mesmo `backend.server` do desenvolvimento, rodando com `--prod` atrás de um **Cloudflare Tunnel**. O servidor não abre porta para a internet: o túnel sai dele até a Cloudflare, que entrega o domínio com HTTPS.

```text
visitante → Cloudflare (HTTPS, cache, proteção) → túnel → 127.0.0.1:8000 (backend.server --prod) → SQLite
```

## O que o modo `--prod` muda

- Respostas da API ficam em cache na memória e saem com `Cache-Control: public, max-age=300`. A chave inclui a data de modificação do banco: trocar o arquivo SQLite invalida o cache sozinho.
- Compressão gzip, `HEAD`, `/healthz` (verifica banco e build) e cabeçalhos de segurança (`X-Frame-Options`, `Referrer-Policy`, `nosniff`).
- Consultas que passam de 8 segundos são abortadas, para uma busca pesada não travar o site.
- Teste local igual à produção: `make prod`.

## Primeira vez

1. **Servidor.** Um VPS Ubuntu pequeno resolve (1 vCPU, 2 GB de RAM, 20 GB de disco: o banco tem cerca de 85 MB). Prepare com:
   `ssh painel 'sudo bash -s' < deploy/setup-server.sh` (com `root`: `ssh root@IP 'bash -s' < ...`)
2. **Configuração local.** `cp .env.example .env` e preencha `SERVER` (o atalho do `~/.ssh/config`, ex.: `painel`). Com usuário comum (`ubuntu`) os comandos usam `sudo`; entrando como root, defina `SUDO=` vazio.
3. **Banco e código.** `make deploy-db` e depois `make deploy`. O `deploy` roda `make check` antes e para se algum teste falhar.
4. **Túnel.** No servidor:
   ```sh
   cloudflared tunnel login                          # abre um link; autorize o domínio
   cloudflared tunnel create painel                  # mostra o TUNNEL_ID
   cloudflared tunnel route dns painel seudominio.com.br
   cloudflared tunnel route dns painel www.seudominio.com.br
   mkdir -p /etc/cloudflared && cp ~/.cloudflared/*.json /etc/cloudflared/
   cp /opt/painel/app/deploy/cloudflared.example.yml /etc/cloudflared/config.yml   # edite TUNNEL_ID e domínio
   cloudflared service install && systemctl enable --now cloudflared
   ```
5. **Cloudflare (painel do site).** SSL/TLS em *Full*; *Always Use HTTPS* ligado.

## Atualizações

| O que mudou | Comando |
|---|---|
| Código ou telas | `make deploy` |
| Banco ou snapshots (nova coleta/importação) | `make db-check` e depois `make deploy-data` (alias `deploy-db`). Os snapshots listados em `deploy/snapshots-local-only.txt` (insumos do custo do mandato) ficam só no computador local |
| Cota do ano corrente | Nada: `painel-ingest.timer` atualiza no servidor todo dia (abaixo). `make deploy-data` continua válido para publicar uma base local, e substitui a do servidor |
| Ver se está no ar | `make deploy-status` |

Logs: `ssh SERVIDOR journalctl -u painel -f`.

## Atualização automática dos dados

A cota da Câmara e do Senado do ano corrente é atualizada todo dia no próprio servidor por
`painel-ingest.timer` (5h40 de Brasília, com até 15 min de atraso aleatório). O timer chama
`python3 -m ingest.pipeline daily`, que executa, nesta ordem, e grava cada etapa em
`/opt/painel/data/status/daily.json` (histórico em `daily-history.jsonl`):

| Etapa | O que faz | Se falhar |
|---|---|---|
| `collect` | `ingest/legislative.py --year <ano corrente>` grava `data/imports/legislative.json` | Fonte indisponível vira execução **parcial** e preserva a fotografia anterior daquela fonte; coletor que morre interrompe |
| `validate` | Confere fontes, ano das notas (nunca importa outro ano no caminho padrão) e o que será substituído | Interrompe antes de tocar o banco |
| `backup` | Cópia consistente em `data/backups/na-lupa-daily-<data>.sqlite3`; mantém as 7 mais recentes | Interrompe |
| `stage` | Copia o banco publicado para `data/pipeline/`; o banco em uso nunca recebe escrita | Interrompe |
| `import` | Importação transacional na cópia (`backend.public_store`) | Transação desfeita; interrompe |
| `verify` | `quick_check`, chaves estrangeiras, versão do esquema e **guarda de regressão**: lista oficial caindo mais de 5% ou notas caindo mais de 10% não são publicadas | Interrompe; a cópia é descartada |
| `publish` | Troca atômica do arquivo do banco (`os.replace`); o cache do site invalida sozinho pela data do arquivo | Recusa se houver `-journal`/`-wal` pendente ao lado do banco |
| `notify` | E-mail em falha e parcial (sucesso só com `PAINEL_MAIL_ON_SUCCESS=1`) e ping opcional no monitor | Falha de envio fica registrada no status |

Só uma execução por vez (lock em `data/status/pipeline.lock`). Os limites da guarda de regressão
são argumentos do comando (`--max-roster-drop`, `--max-expense-drop`); quando uma queda for legítima,
rode uma vez à mão com limites maiores, confira e deixe o timer seguir. O banco, os backups e os
caches ficam em `/opt/painel/data`; `/opt/painel/app/data` é um link para essa pasta, criado pelo
deploy, porque os coletores gravam em `<app>/data`.

Ativar (uma vez), depois do `make deploy`, que instala as unidades:

```sh
sudo install -m 0600 /opt/painel/app/deploy/pipeline.env.example /etc/painel/pipeline.env
sudo nano /etc/painel/pipeline.env                      # destinatário e SMTP (Gmail: senha de app)
sudo systemctl start painel-ingest.service && sudo journalctl -u painel-ingest -n 50   # primeira execução, assistida
sudo systemctl enable --now painel-ingest.timer
```

Acompanhar: `systemctl list-timers painel-ingest.timer`, `journalctl -u painel-ingest -n 100`
e `make deploy-status`, que mostra o último resultado. Teste do e-mail no servidor:
`cd /opt/painel/app && sudo -u painel env $(sudo cat /etc/painel/pipeline.env | xargs) python3 -m ingest.pipeline test-mail`.
Localmente, `make update-daily DRY_RUN=1` faz tudo, menos trocar o banco.

Se o processo morrer sem gravar status (timeout de 2 h, falta de memória), `painel-ingest-failure.service`
envia o aviso de último recurso. O e-mail não detecta o timer que deixou de disparar; para isso,
defina `PAINEL_HEALTHCHECK_URL` com um monitor externo (healthchecks.io ou similar), que avisa
quando o ping diário não chega. Os demais coletores (perfis, projetos, Senado, custo do mandato,
Minha cidade) continuam manuais; a ordem de automação está em [Próximas etapas](roadmap.md).

## Rodar do próprio Mac (temporário)

Para mostrar o site sem servidor: rode `make prod` e, em outro terminal, `cloudflared tunnel run painel` com `~/.cloudflared/config.yml` igual ao exemplo (trocando `/etc/cloudflared/` por `~/.cloudflared/`). O site só fica no ar com o Mac ligado.

## Cuidados

- `.env`, o banco e os backups não vão para o git nem para a pasta do código no servidor.
- Cada ficha oferece o CSV com as notas da pessoa (`/api/c/gastos.csv`); o limite de tempo protege o servidor, mas, se houver abuso, ative *Rate limiting* na Cloudflare para `/api/`.

## Publicação automática pelo GitHub

O workflow `.github/workflows/deploy.yml` roda `make ci` (sintaxe e testes, sem dados privados ou downloads) em todo push e pull request. Em push na `main`, se passar, ele envia o código, instala as unidades do systemd (site e atualização automática) e o servidor monta a página com os snapshots complementares que já estiverem lá (`/opt/painel/data/snapshots`). O build não exige `editorial.json` nem qualquer snapshot; a lista e os totais de parlamentares vêm do SQLite em execução. Banco e snapshots nunca passam pelo GitHub: vão pelo `make deploy-data`, do seu computador. Rode esse comando para publicar uma nova base ou atualizar complementos locais.

Configuração (uma vez):

1. Crie uma chave só para o deploy: `ssh-keygen -t ed25519 -f ~/.ssh/painel-deploy -N "" -C github-deploy`.
2. Autorize-a no servidor: `ssh painel 'cat >> ~/.ssh/authorized_keys' < ~/.ssh/painel-deploy.pub`.
3. No repositório do GitHub, em *Settings > Secrets and variables > Actions*, crie `DEPLOY_HOST` (IP), `DEPLOY_USER` (`ubuntu`) e `DEPLOY_SSH_KEY` (conteúdo de `~/.ssh/painel-deploy`, a chave **privada**).
4. Opcional: em *Settings > Environments*, crie `production` e exija aprovação manual antes de publicar.

## Peso da página

O HTML contém os metadados curtos dos quatro cartões de votação e os complementos pequenos que existirem nos snapshots. O roster, totais e despesas ficam no SQLite e são consultados pela API; o banco completo não é embutido no HTML. Os perfis complementares (`perfis.json`) ficam no servidor e cada ficha busca o seu em `/api/c/perfil/<id>`.

## Endereço público e buscadores

Defina o domínio no servidor para que `sitemap.xml`, `robots.txt` e os endereços canônicos usem sempre o mesmo
endereço. Use um override do systemd: o deploy reinstala `deploy/dashboard.service` a cada publicação, mas não
toca no override.

```sh
sudo mkdir -p /etc/systemd/system/painel.service.d
printf '[Service]\nEnvironment=PAINEL_SITE_URL=https://seudominio.com.br\n' | sudo tee /etc/systemd/system/painel.service.d/site-url.conf
sudo systemctl daemon-reload && sudo systemctl restart painel
```

Sem a variável, o servidor usa o `Host` que o Cloudflare Tunnel repassa.
Depois do deploy, envie `https://seudominio.com.br/sitemap.xml` no Google Search Console e no Bing Webmaster Tools.
