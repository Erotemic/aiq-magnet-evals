"""Fixed-upstream streaming HTTP relay for the private Docker bridge.

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
            try:
                size = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self.send_error(400, "invalid content length")
                return
            if size < 0 or size > 32 * 1024 * 1024 or self.headers.get("Transfer-Encoding"):
                self.send_error(400, "unsupported request framing or size")
                return
            body = self.rfile.read(size) if size else None
            request = urllib.request.Request(upstream + self.path, data=body, method=self.command)
            for key in ("Content-Type", "Authorization"):
                if key in self.headers:
                    request.add_header(key, self.headers[key])
            try:
                response = opener.open(request, timeout=600)
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
                self.send_response(status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                for key in ("Content-Length", "Content-Encoding"):
                    if key in response.headers:
                        self.send_header(key, response.headers[key])
                # HTTP/1.0 close framing works for SSE and upstream chunked
                # responses after urllib removes their transfer encoding.
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                try:
                    while payload := response.read1(64 * 1024):
                        self.wfile.write(payload)
                        self.wfile.flush()
                except (OSError, TimeoutError):
                    # An interrupted stream remains interrupted; never turn
                    # a partial model response into a fabricated success body.
                    self.close_connection = True

        do_GET = forward
        do_POST = forward

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
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
