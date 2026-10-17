#!/usr/bin/env python3
"""Morgoth admin: start / stop / restart the strata systemd user unit over HTTP.

Runs on the host (not in docker) because it drives a host process via systemctl --user.
Auth: HTTP Basic (any user, password = ADMIN_TOKEN) or `Authorization: Bearer ADMIN_TOKEN`.
  GET  /          control page
  GET  /status    {"unit": "active|inactive|...", "api": "ready|down", "models": [...]}
  GET  /logs      last 60 journal lines of the unit
  POST /start | /stop | /restart
"""
import base64, hmac, json, os, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

TOKEN = os.environ["ADMIN_TOKEN"]
UNIT = os.environ.get("STRATA_UNIT", "strata.service")
STRATA_URL = os.environ.get("STRATA_URL", "http://127.0.0.1:2026/v1")
STRATA_KEY = os.environ.get("STRATA_SERVER_MORGOTH_KEY", "")
BIND = (os.environ.get("ADMIN_HOST", "127.0.0.1"), int(os.environ.get("ADMIN_PORT", "2027")))
ACTIONS = ("start", "stop", "restart")

PAGE = """<!doctype html><meta charset=utf-8><title>Strata control</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>body{font:16px system-ui;max-width:48rem;margin:2rem auto;padding:0 1rem;background:#0f172a;color:#e2e8f0}
button{font:inherit;padding:.5rem 1rem;margin-right:.5rem;border:0;border-radius:.4rem;background:#334155;color:#fff;cursor:pointer}
button:disabled{opacity:.5}pre{background:#1e293b;padding:1rem;border-radius:.4rem;overflow:auto;max-height:24rem;font-size:13px}</style>
<h1>Strata control</h1><p id=s>loading…</p>
<p><button onclick="act('start')">Start</button><button onclick="act('restart')">Restart</button><button onclick="act('stop')">Stop</button></p>
<pre id=log></pre>
<script>
const $=id=>document.getElementById(id);
async function refresh(){const r=await(await fetch('status')).json();
$('s').textContent=`service: ${r.unit} · api: ${r.api} · models: ${r.models.join(', ')||'-'}`;
$('log').textContent=await(await fetch('logs')).text();}
async function act(a){for(const b of document.querySelectorAll('button'))b.disabled=true;
const r=await(await fetch(a,{method:'POST'})).json();if(!r.ok)alert(r.stderr||'failed');
for(const b of document.querySelectorAll('button'))b.disabled=false;refresh();}
refresh();setInterval(refresh,5000);
</script>"""


def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args, UNIT], capture_output=True, text=True)


def status():
    unit = systemctl("is-active").stdout.strip()
    try:
        req = Request(f"{STRATA_URL}/models", headers={"Authorization": f"Bearer {STRATA_KEY}"})
        models = [m["id"] for m in json.load(urlopen(req, timeout=3))["data"]]
        api = "ready"
    except Exception:
        models, api = [], "down"
    return {"unit": unit, "api": api, "models": models}


def logs():
    return subprocess.run(["journalctl", "--user", "-u", UNIT, "-n", "60", "--no-pager", "-o", "short-iso"],
                          capture_output=True, text=True).stdout


class Handler(BaseHTTPRequestHandler):
    def _authed(self):
        hdr = self.headers.get("Authorization", "")
        given = ""
        if hdr.startswith("Basic "):
            given = base64.b64decode(hdr[6:], validate=False).decode(errors="replace").partition(":")[2]
        elif hdr.startswith("Bearer "):
            given = hdr[7:].strip()
        if hmac.compare_digest(given, TOKEN):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="morgoth"')
        self.end_headers()
        return False

    def _send(self, code, body, ctype="application/json"):
        data = (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._authed():
            return
        if self.path == "/":
            return self._send(200, PAGE, "text/html")
        if self.path == "/status":
            return self._send(200, status())
        if self.path == "/logs":
            return self._send(200, logs(), "text/plain")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            return
        action = self.path.strip("/")
        if action not in ACTIONS:
            return self._send(404, {"error": "not found"})
        r = systemctl(action)
        self._send(200 if r.returncode == 0 else 500,
                   {"action": action, "ok": r.returncode == 0, "stderr": r.stderr.strip()})

    def log_message(self, fmt, *args):  # journald already timestamps; keep lines short
        print(f"{self.client_address[0]} {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"morgoth admin on http://{BIND[0]}:{BIND[1]} controlling {UNIT}", flush=True)
    ThreadingHTTPServer(BIND, Handler).serve_forever()
