# morgoth

A single front door for a self-hosted LLM box. One reverse proxy, one login page, and a dashboard in
front of a local [Strata](https://github.com/Niko1221/Strata) inference server, a [LiteLLM](https://docs.litellm.ai)
proxy, and whatever else runs on the machine. Built to be published through a single port, for example with
[Tailscale Funnel](https://tailscale.com/kb/1223/funnel).

```
internet ── Tailscale Funnel (TLS) ──> caddy 127.0.0.1:2023
                                          ├─ /            homepage      (login page)
                                          ├─ /admin/      strata control page (login page, token injected)
                                          ├─ /strata/     strata's own chat UI (login page)
                                          ├─ /litellm/    LiteLLM API + UI (its own keys / accounts)
                                          ├─ /hermes/     Hermes Agent gateway (its own login)
                                          └─ /auth/       login + session cookie service
```

Everything except caddy listens on loopback only.

## What's in the box

| Piece | Runs as | Port | Notes |
| --- | --- | --- | --- |
| [caddy](caddy/Caddyfile) | docker | 2023 | path routing, `forward_auth` to the login service |
| [auth](auth/server.py) | docker | 2024 | login page; stateless HMAC-signed session cookie, no database |
| [homepage](homepage/) | docker | 3000 | [gethomepage.dev](https://gethomepage.dev) dashboard with live status widgets |
| [litellm](litellm/config.yaml) + postgres | docker | 4000, 5432 | OpenAI-compatible proxy, virtual keys, logs, spend |
| [admin](admin/server.py) | systemd user unit | 2027 | start / stop / restart the model server, tail its logs |
| strata | systemd user unit | 2026 | the inference server itself, unchanged |

The two Python services use only the standard library and have unit tests.

## Requirements

- Linux with systemd, docker and the compose plugin.
- A working Strata install. The unit file assumes `~/Projects/strata` with a `.venv` and a `strata-<model>.json`
  config; edit [systemd/strata.service](systemd/strata.service) if yours differs.
- This repo checked out at `~/Projects/morgoth` (the admin unit's `EnvironmentFile` points there).

## Quick start

```sh
cp .env.example .env            # fill in every value; generators are noted inline
./install.sh                    # links + enables the user units, starts strata, docker compose up -d
```

Then open http://localhost:2023 and sign in with `WEB_USER` / `WEB_PASSWORD`.

To publish it:

```sh
sudo tailscale funnel --bg 2023
```

`install.sh` is re-runnable. If a strata process is already running outside systemd, it is stopped and started again
as `strata.service` (the model reloads, which takes a minute or two).

## Configuration

All secrets live in `.env` (gitignored). See [.env.example](.env.example) for the list. In short:

| Variable | Used by |
| --- | --- |
| `STRATA_SERVER_MORGOTH_KEY` | strata's API key, passed to LiteLLM and the admin status check |
| `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, `POSTGRES_PASSWORD` | LiteLLM. Never change the salt key after first start |
| `ADMIN_TOKEN` | the control page; caddy injects it after you pass the login page |
| `WEB_USER`, `WEB_PASSWORD`, `AUTH_SECRET` | the login page and its session cookie |
| `HOMEPAGE_ALLOWED_HOSTS` | homepage's host check; set it to your public hostname |

After editing `.env`, `litellm/config.yaml` or `caddy/Caddyfile`:

```sh
systemctl --user restart morgoth-admin.service && docker compose up -d && docker compose restart litellm caddy
```

(bind-mounted config files are not noticed by `up -d`, hence the explicit restart.)

## Using it

LiteLLM is the API everyone should talk to. Base URL `https://<your host>/litellm/v1` (locally
`http://localhost:4000/litellm/v1`), model name from `litellm/config.yaml`, key = `LITELLM_MASTER_KEY` or a virtual
key made in the UI at `/litellm/ui`.

```sh
curl https://<your host>/litellm/v1/chat/completions -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.8-flash-next","messages":[{"role":"user","content":"hi"}]}'
```

The control page at `/admin/` has Start / Restart / Stop buttons and a log tail. The same thing as an API, directly on
the host:

```sh
curl -u admin:$ADMIN_TOKEN http://127.0.0.1:2027/status
curl -u admin:$ADMIN_TOKEN -X POST http://127.0.0.1:2027/restart   # also /start /stop, GET /logs
```

`/auth/logout` ends the browser session.

## LiteLLM UI accounts

On first start, log in to `/litellm/ui` with the master key, create a proper admin user, then keep
`disable_env_credential_login: true` in `litellm/config.yaml` (already set) so the master key can no longer be used to
sign in to the UI.

## Adapting it

- **Different model or server**: change `model_list` in `litellm/config.yaml` and `ExecStart` in
  `systemd/strata.service`. The admin service only needs the unit name (`STRATA_UNIT`) and the `/v1/models` URL.
- **Another service behind the proxy**: add a `handle` block to the Caddyfile and a tile to `homepage/services.yaml`.
  Add `import login` inside a `route { ... }` to put it behind the login page; see the `/admin/` block for the
  prefix-stripping pattern.
- **No Tailscale**: anything that terminates TLS and forwards to `127.0.0.1:2023` works (cloudflared, nginx, caddy
  with a real domain).

## Security notes

- The login page has a one-second delay on failed attempts but no lockout. Use a long random password.
- Sessions last 30 days (`AUTH_TTL_SECONDS`). Rotating `AUTH_SECRET` logs every browser out.
- Services with their own authentication (LiteLLM, Hermes) are deliberately not behind the login page so their API
  clients keep working.
- Without `loginctl enable-linger <user>`, the systemd user units stop when you log out.

## Development

```sh
python3 -m unittest admin/test_admin.py auth/test_auth.py
docker compose config -q
```

See [CLAUDE.md](CLAUDE.md) for the non-obvious decisions.
