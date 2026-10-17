# AI_INSTALL.md — instructions for a coding agent installing morgoth

You are installing the morgoth stack (see [README.md](README.md)) on the operator's machine. Follow the steps in
order, verify each one with the command given, and report what you found. Do not skip a verification. Ask the operator
only the questions listed in step 1; decide everything else yourself from what you find on the machine.

Rules:

- Never print secret values in your replies. Say which file they are in.
- Do not restart the model server more than the install needs; a restart reloads tens of GB and takes minutes.
- Do not change anything inside the Strata checkout. Only this repo and `~/.config/systemd/user/` are yours.
- If a step fails, stop and report the command, its output, and your best guess at the cause. Do not improvise around it.

## 1. Ask the operator

1. Where is Strata installed, and how is it started today? (A `run-*.sh`, a terminal, a systemd unit?) If they don't
   know, you will find out in step 3.
2. Will this be published to the internet, and how? (Tailscale Funnel is what the Caddyfile assumes; anything that
   terminates TLS and forwards to `127.0.0.1:2023` works.) What hostname?
3. Is a Hermes Agent gateway running on this machine? If not, you will remove its route and tile in step 6.
4. Is it acceptable that the running model server is stopped once and restarted under systemd during the install?

## 2. Check the machine

Run and record:

```sh
docker compose version                 # need the compose plugin (v2+)
systemctl --user is-system-running     # need a systemd user session ("running" or "degraded" is fine)
python3 --version                      # 3.10+ for admin/ and auth/ (they use only the stdlib)
loginctl show-user "$USER" -p Linger   # Linger=no means user units stop on logout; see step 9
ss -ltn | awk '{print $4}' | grep -E ':(2019|2023|2024|2027|3000|4000|5432)$'   # must print nothing
id -nG | tr ' ' '\n' | grep -x docker  # user must be in the docker group (or use sudo for docker consistently)
```

If a port is taken, find the owner with `ss -ltnp` and tell the operator before changing any port. Port changes
must be made in all of: `compose.yaml` comments, `caddy/Caddyfile`, `homepage/services.yaml`, the systemd units'
`ExecStart`, and `admin/server.py` / `auth/server.py` defaults (`ADMIN_PORT`, `AUTH_PORT`).

## 3. Learn how Strata runs

Find the process and its config:

```sh
pgrep -af 'serve/server.py --engine strata'
```

From its command line note: the python interpreter path, `serve/server.py` path, the `--config` JSON path, the
`--port`. Then read the JSON config and note `api_key`, `model_name`, and the `--max-context` value inside `args`.
Confirm the API answers:

```sh
curl -s -H "Authorization: Bearer <api_key>" http://127.0.0.1:<port>/v1/models
```

The `id` in that response is the model id LiteLLM must use. If Strata is not running, ask the operator to start it
once the normal way so you can read these values, or read them from the JSON config directly.

Check how the process is owned: `systemctl --user status <pid>`. If it is in an `app-*.scope` or a terminal, it is not
a service yet and step 7 will move it. If it already is a user unit, use that unit's name as `STRATA_UNIT` and skip
installing `systemd/strata.service`.

## 4. Clone and adapt paths

```sh
git clone <this repo> ~/Projects/morgoth && cd ~/Projects/morgoth
```

The units assume `~/Projects/morgoth` (admin's `EnvironmentFile`) and `~/Projects/strata` with a `.venv` and the
config JSON. Edit [systemd/strata.service](systemd/strata.service) `ExecStart` to exactly match the command line
found in step 3, minus any `--open` flag (it would try to open a browser). Edit `WorkingDirectory` to the Strata
checkout. If the repo is somewhere else than `~/Projects/morgoth`, edit `EnvironmentFile` in
[systemd/morgoth-admin.service](systemd/morgoth-admin.service) and the `%h/Projects/morgoth` references.

If Strata's port is not 2026, also change `STRATA_URL` (add `Environment=STRATA_URL=http://127.0.0.1:<port>/v1` to
the admin unit), the `api_base` in `litellm/config.yaml`, and the `/strata/` upstream in the Caddyfile.

## 5. Create `.env`

```sh
cp .env.example .env && chmod 600 .env
```

Fill every variable. Generate secrets with `openssl rand -hex 32` and passwords with `openssl rand -hex 16`. Use the
Strata `api_key` from step 3 for `STRATA_SERVER_MORGOTH_KEY`. `LITELLM_MASTER_KEY` and `LITELLM_SALT_KEY` should
start with `sk-`. Set `HOMEPAGE_ALLOWED_HOSTS` to the public hostname from step 1 (or leave `*` if unknown yet).
Choose `WEB_USER` with the operator; it is their login name. Verify no value is empty:

```sh
grep -E '=\s*(#|$)' .env   # must print nothing
```

## 6. Adapt the configs

- `litellm/config.yaml`: set `model: openai/<model id from step 3>`, keep or rename `model_name` (this is what API
  clients will send), and set the three `max_*_tokens` to Strata's `--max-context`.
- `caddy/Caddyfile`: if there is no Hermes gateway, delete the `redir /hermes` line and the `handle /hermes/*` block.
  If other local services should be reachable, add a `handle` block per the README's "Adapting it" section.
- `homepage/services.yaml`: remove the `Agents` group if Hermes is absent. Keep `href`s path-relative so they work
  through the proxy.
- Validate: `docker compose config -q` must be silent.

## 7. Install

Tell the operator the model server will restart now (if step 1.4 was yes), then:

```sh
./install.sh
```

It symlinks the units, enables them, moves a bare Strata process into `strata.service`, and runs
`docker compose up -d`. Then wait for the model:

```sh
. ./.env; until curl -sf -u admin:$ADMIN_TOKEN http://127.0.0.1:2027/status | grep -q '"api": "ready"'; do sleep 5; done
```

If the unit fails, read `journalctl --user -u strata.service -n 50` and compare `ExecStart` with step 3 before anything
else; a wrong path or a missing `lib_dirs` CUDA path in the JSON config are the usual causes.

## 8. Verify everything

Run all of these; every line must match the expected result.

```sh
. ./.env
systemctl --user is-active strata.service morgoth-admin.service          # active, active
docker compose ps --format '{{.Name}} {{.Status}}'                       # caddy, auth, homepage, litellm, litellm-db all Up
ss -ltn | awk '{print $4}' | grep -E ':(2023|2024|3000|4000|5432|2027)$'  # every line starts with 127.0.0.1
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:2023/           # 302 (to /auth/login)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:2023/auth/login # 200
curl -s -o /dev/null -c /tmp/cj -w '%{http_code}\n' -d "username=$WEB_USER&password=$WEB_PASSWORD&rd=/" http://127.0.0.1:2023/auth/login   # 303
curl -s -o /dev/null -b /tmp/cj -w '%{http_code}\n' http://127.0.0.1:2023/          # 200
curl -s -b /tmp/cj http://127.0.0.1:2023/admin/status                               # {"unit": "active", "api": "ready", ...}
curl -s http://127.0.0.1:2023/litellm/health/readiness                              # {"status":"healthy","db":"connected"}
curl -s http://127.0.0.1:2023/litellm/v1/chat/completions -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"<model_name from litellm/config.yaml>","messages":[{"role":"user","content":"Reply with exactly: ok"}],"max_tokens":200}'
rm -f /tmp/cj
python3 -m unittest admin/test_admin.py auth/test_auth.py              # OK
```

The chat response's `content` may be empty if `max_tokens` is too small for a reasoning model; raise it rather than
assuming a failure.

## 9. LiteLLM UI account, then lock the env login

Fresh installs have `disable_env_credential_login: true` in `litellm/config.yaml`, which also blocks signing in with
the master key, so nobody can reach the UI yet. Do this once, and finish it in the same sitting: while the env login is
enabled, anyone with the master key can sign in as a proxy admin, so it must be disabled again as soon as the operator's
own account exists. Do not leave step 3 for later.

1. Comment out that line, `docker compose restart litellm`, wait for `/litellm/health/readiness`.
2. Tell the operator to open `http://localhost:2023/litellm/ui`, sign in with username `admin` and the master key as
   password, and create their own admin user (Internal Users → Invite User, role Proxy Admin, set a password).
3. Uncomment the line, `docker compose restart litellm`. Verify the master-key login is now refused:
   `curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:4000/litellm/login -d "username=admin&password=$LITELLM_MASTER_KEY"`
   must print `401`.

## 10. Publish and persist

- Tailscale Funnel: the operator runs `sudo tailscale funnel --bg 2023`, then `tailscale funnel status` must show
  `/ proxy http://127.0.0.1:2023`. Verify from outside the machine if possible:
  `curl -s -o /dev/null -w '%{http_code}\n' https://<host>/` → `302`.
- Set `HOMEPAGE_ALLOWED_HOSTS` to the public host if it was `*`, then `docker compose up -d homepage`.
- If step 2 showed `Linger=no`, the operator runs `loginctl enable-linger $USER` (may need sudo) so the user units
  survive logout. Verify with `loginctl show-user "$USER" -p Linger` → `Linger=yes`.

## 11. Hand-off

Report to the operator, without secret values:

- URLs: the public host, and locally `http://localhost:2023`, the LiteLLM API base `/litellm/v1`, the model name.
- Where credentials live: `.env` (login page user/password, master key, admin token).
- How to restart things: the control page at `/admin/`, or `systemctl --user restart strata.service`.
- The one-liner to apply config changes from the README.
- Anything you could not verify, named explicitly.
