#!/usr/bin/env bash
# Prepara um servidor Ubuntu/Debian novo para o Painel Público. Rode uma vez, como root:
#   ssh root@SERVIDOR 'bash -s' < deploy/setup-server.sh
set -euo pipefail

apt-get update -y
apt-get install -y python3 rsync sqlite3 curl ufw
id painel >/dev/null 2>&1 || useradd --system --home /opt/painel --shell /usr/sbin/nologin painel
install -d -o painel -g painel /opt/painel /opt/painel/app /opt/painel/data
# Os coletores gravam em <app>/data; no servidor isso aponta para a pasta de dados fora do código.
ln -sfn /opt/painel/data /opt/painel/app/data
# Variáveis da atualização automática (e-mail); modelo em deploy/pipeline.env.example.
install -d -m 0750 /etc/painel

# cloudflared (repositório oficial da Cloudflare)
if ! command -v cloudflared >/dev/null; then
  install -d -m 0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -y && apt-get install -y cloudflared
fi

# Firewall: só SSH. O site não abre porta; o túnel sai do servidor para a Cloudflare.
ufw allow OpenSSH
ufw --force enable
echo "Pronto. Próximo passo no seu computador: make deploy-db SERVER=root@ESTE_SERVIDOR e make deploy SERVER=root@ESTE_SERVIDOR"
echo "Depois, para a atualização automática: copie deploy/pipeline.env.example para /etc/painel/pipeline.env e rode systemctl enable --now painel-ingest.timer"
