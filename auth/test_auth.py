"""Self-check: cookie signing, verify gate, login flow, open-redirect guard. Run: python3 -m unittest auth/test_auth.py"""
import os, sys, threading, time, unittest, urllib.error, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer

os.environ.update(WEB_USER="u", WEB_PASSWORD="p", AUTH_SECRET="s")
sys.path.insert(0, os.path.dirname(__file__))
import server as auth


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class AuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), auth.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"
        cls.open = urllib.request.build_opener(NoRedirect()).open

    def req(self, path, data=None, headers=None):
        r = urllib.request.Request(self.url + path, data=data, headers=headers or {})
        try:
            resp = self.open(r)
            return resp.status, resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.headers

    def test_token(self):
        self.assertTrue(auth.valid(auth.make_token()))
        self.assertFalse(auth.valid("garbage"))
        self.assertFalse(auth.valid(f"{int(time.time())-1}.{auth.sign(int(time.time())-1)}"))  # expired
        exp = int(time.time()) + 100
        self.assertFalse(auth.valid(f"{exp}.{auth.sign(exp)[:-1]}0"))  # tampered signature

    def test_verify_redirects_then_passes(self):
        code, h = self.req("/auth/verify", headers={"X-Forwarded-Uri": "/admin/"})
        self.assertEqual((code, h["Location"]), (302, "/auth/login?rd=%2Fadmin%2F"))
        code, h = self.req("/auth/verify", headers={"Cookie": f"{auth.COOKIE}={auth.make_token()}"})
        self.assertEqual(code, 200)

    def test_login_page_renders(self):
        r = urllib.request.urlopen(self.url + "/auth/login?rd=%2Fadmin%2F&e=1").read().decode()
        self.assertIn('name=rd value="/admin/"', r); self.assertIn("Wrong username", r)

    def test_login(self):
        bad = urllib.parse.urlencode({"username": "u", "password": "wrong", "rd": "/x"}).encode()
        code, h = self.req("/auth/login", data=bad)
        self.assertEqual((code, h["Location"]), (303, "/auth/login?e=1&rd=%2Fx"))
        good = urllib.parse.urlencode({"username": "u", "password": "p", "rd": "//evil.example"}).encode()
        code, h = self.req("/auth/login", data=good, headers={"X-Forwarded-Proto": "https"})
        self.assertEqual((code, h["Location"]), (303, "/"))  # open redirect blocked
        self.assertIn("HttpOnly", h["Set-Cookie"]); self.assertIn("Secure", h["Set-Cookie"])
        self.assertTrue(auth.valid(h["Set-Cookie"].split(";")[0].split("=", 1)[1]))
        code, h = self.req("/auth/logout")
        self.assertIn("Max-Age=0", h["Set-Cookie"])


if __name__ == "__main__":
    unittest.main()
