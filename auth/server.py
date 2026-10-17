#!/usr/bin/env python3
"""Login page + forward-auth backend for caddy. Stateless: the session cookie is "<expiry>.<hmac(expiry)>".

  GET  /auth/verify   200 when the cookie is valid, else 302 to /auth/login?rd=<original uri>
  GET  /auth/login    login form      POST /auth/login    check user/password, set cookie, redirect to rd
  GET  /auth/logout   clear cookie
"""
import hashlib, hmac, html, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

USER, PASSWORD, SECRET = os.environ["WEB_USER"], os.environ["WEB_PASSWORD"], os.environ["AUTH_SECRET"]
TTL = int(os.environ.get("AUTH_TTL_SECONDS", str(30 * 24 * 3600)))
BIND = ("127.0.0.1", int(os.environ.get("AUTH_PORT", "2024")))
COOKIE = "morgoth_session"

PAGE = """<!doctype html><html lang=en><meta charset=utf-8><title>Morgoth · sign in</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{color-scheme:dark}
body{margin:0;min-height:100vh;display:grid;place-items:center;font:16px/1.4 system-ui,sans-serif;
background:radial-gradient(80rem 40rem at 50% -10%,#1e293b,#0b1120 60%);color:#e2e8f0}
form{width:min(22rem,calc(100vw - 2rem));padding:2rem;border-radius:1rem;background:#0f172acc;
border:1px solid #1e293b;box-shadow:0 20px 60px #0008;backdrop-filter:blur(8px)}
h1{margin:0 0 .25rem;font-size:1.5rem;letter-spacing:.02em}p{margin:0 0 1.5rem;color:#94a3b8;font-size:.9rem}
label{display:block;margin:.9rem 0 .3rem;font-size:.8rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em}
input{width:100%;box-sizing:border-box;padding:.7rem .8rem;border-radius:.5rem;border:1px solid #334155;
background:#020617;color:inherit;font:inherit}input:focus{outline:2px solid #38bdf8;border-color:transparent}
button{margin-top:1.4rem;width:100%;padding:.75rem;border:0;border-radius:.5rem;background:#38bdf8;color:#082f49;
font:inherit;font-weight:600;cursor:pointer}button:hover{background:#7dd3fc}
.err{margin:0 0 1rem;padding:.6rem .8rem;border-radius:.5rem;background:#7f1d1d55;border:1px solid #991b1b;color:#fecaca;font-size:.9rem}
</style>
<form method=post action=/auth/login autocomplete=on>
<h1>Morgoth</h1><p>Sign in to continue</p>{{error}}
<input type=hidden name=rd value="{{rd}}">
<label for=u>Username</label><input id=u name=username required autofocus autocomplete=username>
<label for=p>Password</label><input id=p name=password type=password required autocomplete=current-password>
<button>Sign in</button></form></html>"""


def sign(exp):
    return hmac.new(SECRET.encode(), str(exp).encode(), hashlib.sha256).hexdigest()


def make_token():
    exp = int(time.time()) + TTL
    return f"{exp}.{sign(exp)}"


def valid(token):
    exp, _, sig = (token or "").partition(".")
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, sign(int(exp)))


def safe_rd(rd):  # same-origin paths only, no open redirect ("//evil")
    return rd if rd.startswith("/") and not rd.startswith("//") else "/"


class Handler(BaseHTTPRequestHandler):
    def _cookie(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def _redirect(self, to, code=302, cookie=None):
        self.send_response(code)
        self.send_header("Location", to)
        if cookie is not None:
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "http") == "https" else ""
            max_age = TTL if cookie else 0
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _page(self, rd, error=False):
        body = PAGE.replace("{{rd}}", html.escape(rd, quote=True)).replace(
            "{{error}}", '<p class=err>Wrong username or password.</p>' if error else "")
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/auth/verify":
            if valid(self._cookie()):
                self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()
            else:
                rd = safe_rd(self.headers.get("X-Forwarded-Uri", "/"))
                self._redirect(f"/auth/login?rd={quote(rd, safe='')}")
        elif url.path == "/auth/login":
            self._page(safe_rd(q.get("rd", ["/"])[0]), error="e" in q)
        elif url.path == "/auth/logout":
            self._redirect("/auth/login", cookie="")
        else:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()

    def do_POST(self):
        if urlparse(self.path).path != "/auth/login":
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        n = min(int(self.headers.get("Content-Length", "0")), 4096)
        form = parse_qs(self.rfile.read(n).decode(errors="replace"))
        user, pw = form.get("username", [""])[0], form.get("password", [""])[0]
        rd = safe_rd(form.get("rd", ["/"])[0])
        ok = hmac.compare_digest(user.encode(), USER.encode()) & hmac.compare_digest(pw.encode(), PASSWORD.encode())
        if ok:
            self._redirect(rd, 303, cookie=make_token())
        else:
            time.sleep(1)  # shortcut: slows guessing a little; add real rate limiting if this ever faces the open internet unfunneled
            self._redirect(f"/auth/login?e=1&rd={quote(rd, safe='')}", 303)

    def log_message(self, fmt, *args):
        print(f"{self.headers.get('X-Forwarded-For', self.client_address[0])} {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"morgoth auth on http://{BIND[0]}:{BIND[1]}", flush=True)
    ThreadingHTTPServer(BIND, Handler).serve_forever()
