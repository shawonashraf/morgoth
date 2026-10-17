# morgoth

Single front door for this machine's services. Strata keeps running as before on `127.0.0.1:2026`.

Caddy on `127.0.0.1:2023` is the one port to publish (Tailscale Funnel 443 -> 2023). Everything else is loopback-only.

| Path behind caddy | What | Login | Runs as |
| --- | --- | --- | --- |
| `/` | Homepage (gethomepage.dev) | login page | docker `homepage` (:3000) |
| `/litellm/v1`, `/litellm/ui` | LiteLLM proxy + UI | its own keys / UI account | docker `litellm` + `litellm-db` (:4000) |
| `/admin/` | Strata control page | login page | host: `morgoth-admin.service` (:2027) |
| `/strata/` | Strata's own chat UI | login page + strata key | host: `strata.service` (:2026) |
| `/hermes/` | Hermes Agent gateway | its own login | host process started by you (:9119) |
| not proxied | Cockpit | Linux account | host: `cockpit.socket` (:9090, all interfaces) |

Locally: http://localhost:2023. Publicly, once the funnel is on: `https://<your host>`.

## Logins

- **LiteLLM UI**: the admin account created in the UI (stored in postgres). The shared env login is disabled
  (`disable_env_credential_login: true` in `litellm/config.yaml`).
- **LiteLLM API**: `LITELLM_MASTER_KEY` from `.env`, or a virtual key made in the UI. Base URL
  `http://localhost:4000/litellm/v1` locally or `https://<funnel host>/litellm/v1`, model `qwen3.8-flash-next`.
- **Homepage, control page, strata UI**: the login page at `/auth/login`, `WEB_USER` / `WEB_PASSWORD` from `.env`.
  `auth/server.py` sets a signed session cookie (30 days, `AUTH_SECRET`); `/auth/logout` clears it. Caddy injects
  `ADMIN_TOKEN` towards the control page, so there is no second prompt. Direct access to :2027 still takes
  `ADMIN_TOKEN` (any username, or `Authorization: Bearer`).
- **Cockpit**: your Linux account.

Secrets live in `.env` (gitignored, see `.env.example`).

## Run

```sh
./install.sh            # links + enables the two user units, starts strata, docker compose up -d
docker compose up -d    # just the containers
systemctl --user restart strata.service   # or use the control page / API below
```

After editing `.env`, `litellm/config.yaml` or `caddy/Caddyfile`:

```sh
systemctl --user restart morgoth-admin.service && docker compose up -d && docker compose restart litellm caddy
```

Tailscale Funnel (once, needs root or the tailscale operator):

```sh
sudo tailscale funnel --bg 2023
tailscale funnel status
```

Control API:

```sh
curl -u admin:$ADMIN_TOKEN http://127.0.0.1:2027/status
curl -u admin:$ADMIN_TOKEN -X POST http://127.0.0.1:2027/restart   # also /start /stop, GET /logs
```

Chat through the proxy:

```sh
curl http://127.0.0.1:2023/litellm/v1/chat/completions -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.8-flash-next","messages":[{"role":"user","content":"hi"}]}'
```

## Layout

```
compose.yaml            caddy + homepage + litellm + postgres, all on the host network
caddy/Caddyfile         path routing + forward_auth; the only published port
auth/server.py          login page + session cookie (forward-auth backend), stdlib python; auth/test_auth.py
homepage/               gethomepage config (services.yaml is the tile list)
litellm/config.yaml     model list + general_settings
admin/server.py         control page, stdlib python, no deps; admin/test_admin.py
systemd/*.service       user units, symlinked into ~/.config/systemd/user by install.sh
```

## Notes

- Containers use the host network because strata only listens on loopback.
- The admin service is not a container: it must call `systemctl --user` on the host.
- Everything binds to localhost except Cockpit (`*:9090`), which is not behind caddy; use `tailscale serve`
  (tailnet-only) for it if needed.
- LiteLLM runs with `SERVER_ROOT_PATH=/litellm`, so its local API is also under `/litellm` on :4000.
- New login password: edit `WEB_PASSWORD` in `.env`, then `docker compose up -d auth`. Rotating `AUTH_SECRET` logs
  every browser out.
- `loginctl enable-linger <user>` keeps the user units alive without a login session.
- Tests: `python3 -m unittest admin/test_admin.py auth/test_auth.py`
