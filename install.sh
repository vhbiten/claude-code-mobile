#!/usr/bin/env bash
# install.sh: liga o painel como serviço do seu usuário e publica só na sua rede da Tailscale.
#
#   ./install.sh            instala (ou atualiza) e mostra o endereço pra abrir no celular
#   ./install.sh --remover  desliga os serviços e tira a porta da Tailscale (os dados ficam)
#
# Variáveis opcionais: PAINEL_PORTA (local, 8481), PAINEL_PORTA_TS (tailnet, 8445),
# PAINEL_TMUX (nome da sessão do tmux, "claude").
set -euo pipefail

RAIZ=$(cd "$(dirname "$0")" && pwd)
PORTA_LOCAL=${PAINEL_PORTA:-8481}
PORTA_TS=${PAINEL_PORTA_TS:-8445}
SESSAO=${PAINEL_TMUX:-claude}
UNIDADES="$HOME/.config/systemd/user"
SHELL_LOGIN=${SHELL:-/bin/bash}

for cmd in python3 tmux tailscale claude systemctl; do
  command -v "$cmd" >/dev/null || { echo "install: falta o comando '$cmd'" >&2; exit 1; }
done

if [ "${1:-}" = --remover ]; then
  tailscale serve --https="$PORTA_TS" off >/dev/null 2>&1 || true
  systemctl --user disable --now claude-painel.service claude-tmux.service 2>/dev/null || true
  rm -f "$UNIDADES/claude-painel.service" "$UNIDADES/claude-tmux.service"
  systemctl --user daemon-reload
  echo "painel removido (anexos, entregas e config continuam em $RAIZ)"
  exit 0
fi

# Notificações (Web Push) precisam do pacote cryptography; o resto é só a biblioteca padrão.
[ -x "$RAIZ/.venv/bin/python" ] || python3 -m venv "$RAIZ/.venv"
"$RAIZ/.venv/bin/python" -m pip install -q --upgrade pip cryptography

mkdir -p "$UNIDADES"
# Sessão do tmux onde o Claude roda. 79x70 fixo: sem nenhum terminal ligado o tmux usaria
# 80x24, curto demais pros menus do Claude.
cat > "$UNIDADES/claude-tmux.service" <<EOF
[Unit]
Description=Sessão tmux "$SESSAO" com o Claude Code (comandada pelo painel)

[Service]
Type=forking
ExecStart=$(command -v tmux) new-session -d -s $SESSAO -x 79 -y 70 -c %h "$SHELL_LOGIN -lic 'claude; exec $SHELL_LOGIN -l'"
ExecStop=-$(command -v tmux) kill-session -t $SESSAO
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

cat > "$UNIDADES/claude-painel.service" <<EOF
[Unit]
Description=Painel do Claude Code pro celular (só na tailnet, porta $PORTA_TS)
After=claude-tmux.service

[Service]
Environment=PAINEL_TMUX=$SESSAO PAINEL_PORTA_TS=$PORTA_TS
ExecStart=$(command -v python3) -I $RAIZ/bin/painel-servidor.py $PORTA_LOCAL
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now claude-tmux.service claude-painel.service

# HTTPS com o certificado da Tailscale, visível só pra sua rede (serve, nunca funnel).
if ! tailscale serve --bg --https="$PORTA_TS" "http://127.0.0.1:$PORTA_LOCAL" >/dev/null; then
  echo "install: a Tailscale recusou. Rode uma vez: sudo tailscale set --operator=\$USER" >&2
  exit 1
fi

HOST=$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
echo
echo "Pronto. No celular (com a Tailscale ligada), abra:"
echo "  https://$HOST:$PORTA_TS/"
echo "No iPhone: Compartilhar > Adicionar à Tela de Início (as notificações só funcionam assim)."
echo "Pra subir sem precisar fazer login no PC: loginctl enable-linger \$USER"
