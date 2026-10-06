"""Fixed-upstream HTTP relay for the Phase 0 private Docker bridge probe.

No arbitrary URL forwarding, published container ports, or host networking.
The host hop binds to the Docker bridge gateway and forwards to loopback;
the task can only allowlist the separate container relay's address.
"""
from __future__ import annotations

import contextlib
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@contextlib.contextmanager
def relay(upstream: str, bind: str, port: int = 0):
    upstream = upstream.rstrip("/")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    class Handler(BaseHTTPRequestHandler):
        def forward(self):
            if not self.path.startswith("/") or self.path.startswith("//"):
                self.send_error(400)
                return
            size = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(size) if size else None
            request = urllib.request.Request(upstream + self.path, data=body, method=self.command)
            for key in ("Content-Type", "Authorization"):
                if key in self.headers:
                    request.add_header(key, self.headers[key])
            try:
                response = opener.open(request, timeout=10)
            except urllib.error.HTTPError as exc:
                response = exc
            except urllib.error.URLError:
                self.send_error(502, "upstream unreachable")
                return
            with response:
                status = response.status
                if not isinstance(status, int):
                    self.send_error(502, "invalid upstream status")
                    return
                payload = response.read()
                self.send_response(status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        do_GET = forward
        do_POST = forward

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer((bind, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def main(argv=True):
    import kwconf

    class Config(kwconf.Config):
        upstream = kwconf.Value(None, required=True)
        bind = kwconf.Value("0.0.0.0")
        port = kwconf.Value(8080, type=int)

    args = Config.cli(argv=argv, strict=True, special_options=False)
    with relay(args.upstream, args.bind, args.port):
        threading.Event().wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
