"""Self-check: auth gate and the systemctl calls. Run: ADMIN_TOKEN=x python3 -m unittest admin/test_admin.py"""
import base64, json, os, subprocess, sys, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

os.environ.setdefault("ADMIN_TOKEN", "test-token")
os.environ["STRATA_URL"] = "http://127.0.0.1:9"  # nothing listens: api must read "down"
sys.path.insert(0, os.path.dirname(__file__))
import server as admin


class AdminTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = tempfile.mkdtemp()
        cls.calls = os.path.join(cls.bin, "calls")
        fake = os.path.join(cls.bin, "systemctl")
        with open(fake, "w") as f:
            f.write(f'#!/bin/sh\necho "$@" >> {cls.calls}\n[ "$2" = is-active ] && echo active\nexit 0\n')
        os.chmod(fake, 0o755)
        os.environ["PATH"] = cls.bin + os.pathsep + os.environ["PATH"]
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), admin.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"

    def req(self, path, method="GET", auth=None):
        r = urllib.request.Request(self.url + path, method=method)
        if auth:
            r.add_header("Authorization", auth)
        with urllib.request.urlopen(r) as resp:
            return resp.status, resp.read()

    def test_rejects_missing_and_wrong_token(self):
        for auth in (None, "Bearer nope", "Basic " + base64.b64encode(b"admin:nope").decode()):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.req("/status", auth=auth)
            self.assertEqual(cm.exception.code, 401)

    def test_status_and_restart(self):
        basic = "Basic " + base64.b64encode(b"admin:test-token").decode()
        code, body = self.req("/status", auth=basic)
        self.assertEqual((code, json.loads(body)["unit"], json.loads(body)["api"]), (200, "active", "down"))
        code, body = self.req("/restart", "POST", "Bearer test-token")
        self.assertTrue(json.loads(body)["ok"])
        self.assertIn("--user restart strata.service", open(self.calls).read())
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.req("/rm-rf", "POST", basic)
        self.assertEqual(cm.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
