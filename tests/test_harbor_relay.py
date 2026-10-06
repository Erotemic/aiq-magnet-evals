"""The production bridge must forward tokens before generation completes."""
import contextlib
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from magnet_evals.backends.harbor.relay import relay


def test_streaming_and_shutdown_with_live_response():
    finish = threading.Event()
    connected = threading.Event()

    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == '/v1/stream'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(b'data: first\n\n')
            self.wfile.flush()
            connected.set()
            finish.wait(10)
            with contextlib.suppress(OSError):
                self.wfile.write(b'data: last\n\n')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with relay(f'http://127.0.0.1:{server.server_port}', '127.0.0.1') as port:
            response = urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/stream', timeout=3)
            assert connected.wait(3)
            assert response.headers['Content-Type'] == 'text/event-stream'
            assert response.read1(100) == b'data: first\n\n'
            # Context shutdown must return with an in-flight generation.
        assert not finish.is_set()
        finish.set()
        response.close()
    finally:
        finish.set()
        server.shutdown()
        server.server_close()
        thread.join()
