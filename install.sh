#!/bin/sh
# Installs the two host-side systemd user units and starts the docker stack.
# Re-runnable. Moves a strata that is running outside systemd into the unit.
set -eu
cd "$(dirname "$0")"
mkdir -p ~/.config/systemd/user
ln -sf "$PWD/systemd/strata.service" "$PWD/systemd/morgoth-admin.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable morgoth-admin.service strata.service
systemctl --user restart morgoth-admin.service

if ! systemctl --user is-active -q strata.service && pgrep -f 'serve/server.py --engine strata' >/dev/null; then
  echo "stopping the strata started outside systemd, then starting it as strata.service (model reload ~1-2 min)"
  pkill -f 'serve/server.py --engine strata'
  while pgrep -f 'serve/server.py --engine strata' >/dev/null; do sleep 1; done
fi
systemctl --user start strata.service

docker compose up -d
echo "homepage  http://localhost:3000"
echo "litellm   http://localhost:4000/ui  (login: your LiteLLM admin account)"
echo "admin     http://localhost:2027     (user: admin, password: ADMIN_TOKEN in .env)"
echo "note: 'loginctl enable-linger $USER' (needs sudo) keeps the user units running when you log out"
