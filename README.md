# morgoth

Single front door for this machine's services. Strata keeps running as before on `127.0.0.1:2026`.

| What | Where | Runs as |
| --- | --- | --- |
| Homepage (gethomepage.dev) | http://localhost:3000 | docker `homepage` |
| LiteLLM proxy + UI | http://localhost:4000/v1 · /ui | docker `litellm` + `litellm-db` (postgres) |
| Strata control page | http://localhost:2027 | host: `morgoth-admin.service` (systemd --user) |
| Cockpit | https://localhost:9090 | host: `cockpit.socket` |
| Strata inference | http://127.0.0.1:2026/v1 | host: `strata.service` (systemd --user) |

## Logins

- **LiteLLM UI**: the admin account created in the UI (stored in postgres). The shared env login is disabled
  (`disable_env_credential_login: true` in `litellm/config.yaml`).
- **LiteLLM API**: `LITELLM_MASTER_KEY` from `.env`, or a virtual key made in the UI. Base URL `http://localhost:4000/v1`,
  model `qwen3.8-flash-next`.
- **Control page**: HTTP Basic, any username, password = `ADMIN_TOKEN` from `.env`. Also accepts `Authorization: Bearer ADMIN_TOKEN`.
- **Cockpit**: your Linux account.

Secrets live in `.env` (gitignored, see `.env.example`).

## Run

```sh
./install.sh            # links + enables the two user units, starts strata, docker compose up -d
docker compose up -d    # just the containers
systemctl --user restart strata.service   # or use the control page / API below
```

After editing `.env`:

```sh
systemctl --user restart morgoth-admin.service && docker compose up -d
```

Control API:

```sh
curl -u admin:$ADMIN_TOKEN http://127.0.0.1:2027/status
curl -u admin:$ADMIN_TOKEN -X POST http://127.0.0.1:2027/restart   # also /start /stop, GET /logs
```

Chat through the proxy:

```sh
curl http://127.0.0.1:4000/v1/chat/completions -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.8-flash-next","messages":[{"role":"user","content":"hi"}]}'
```

## Layout

```
compose.yaml            homepage + litellm + postgres, all on the host network
homepage/               gethomepage config (services.yaml is the tile list)
litellm/config.yaml     model list + general_settings
admin/server.py         control page, stdlib python, no deps; admin/test_admin.py
systemd/*.service       user units, symlinked into ~/.config/systemd/user by install.sh
```

## Notes

- Containers use the host network because strata only listens on loopback.
- The admin service is not a container: it must call `systemctl --user` on the host.
- Everything binds to localhost except Cockpit (`*:9090`). For the Cloudflare tunnel later: point the tunnel at
  `:3000`, `:4000`, `:2027`, set `HOMEPAGE_ALLOWED_HOSTS` to the domain, and change the `href`s in
  `homepage/services.yaml` from localhost to the domain. Keep Cockpit off the tunnel or behind Cloudflare Access.
- `loginctl enable-linger <user>` keeps the user units alive without a login session.
- Test: `python3 -m unittest admin/test_admin.py`
