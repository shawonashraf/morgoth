# morgoth

Homepage + LiteLLM proxy + control page for the strata LLM server on this machine. Read README.md for URLs and logins.

## Facts that are not obvious from the files

- Strata (`~/Projects/strata`) is a separate project. Do not edit it from here. It binds `127.0.0.1:2026`, which is
  why every container runs with `network_mode: host`.
- `strata.service` and `morgoth-admin.service` are **systemd user units**, not containers. The unit files in
  `systemd/` are symlinked into `~/.config/systemd/user/`; edit them here, then `systemctl --user daemon-reload`.
- `.env` holds all secrets and is read by both docker compose and `morgoth-admin.service` (EnvironmentFile).
  After changing it: `systemctl --user restart morgoth-admin.service && docker compose up -d`.
- `LITELLM_SALT_KEY` must never change once set; it encrypts credentials stored in postgres.
- LiteLLM env-credential login is disabled on purpose. The only UI login is the admin account in the database.
  Do not add `UI_USERNAME` / `UI_PASSWORD` back.
- The control page checks only the password (`ADMIN_TOKEN`); the username is ignored. Behind caddy (`/admin/`)
  caddy's basic auth is the login and it injects the token itself.
- Caddy (`caddy/Caddyfile`, `127.0.0.1:2023`) is the only port exposed by Tailscale Funnel. Caddy's admin API sits on
  its default `127.0.0.1:2019`, so do not reuse 2019. `WEB_PASSWORD_HASH` in `.env` must stay single-quoted.
- LiteLLM uses `SERVER_ROOT_PATH=/litellm`; its API is `/litellm/v1` everywhere, including on :4000 directly.
- Bind-mounted configs (`litellm/config.yaml`, `caddy/Caddyfile`) need `docker compose restart <svc>`; `up -d` won't notice.

## Working here

- Keep the admin service dependency-free (python3 stdlib). Run `python3 -m unittest admin/test_admin.py` after touching it.
- Validate compose changes with `docker compose config -q` before `up`.
- Restarting `strata.service` reloads ~50 GB of model weights and takes 1-3 minutes. Do not restart it to "check" things;
  use `curl -u admin:$ADMIN_TOKEN http://127.0.0.1:2027/status` instead.
- Nothing here is committed automatically. Do not commit or push unless asked.
