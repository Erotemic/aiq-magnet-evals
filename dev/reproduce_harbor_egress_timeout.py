"""Run with sudo unshare --net: Python, pinned gost binary, output directory.

This CPU-only probe uses a fresh network namespace. An owner-specific OUTPUT
redirect sends only the nobody client's HTTP request through the stock Harbor
GOST red handler; no host firewall rule or model request is involved.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    import kwconf

    class Config(kwconf.Config):
        binary = kwconf.Value(None, type=str, position=1, required=True)
        output = kwconf.Value(None, type=str, position=2, required=True)

    args = Config.cli()
    if os.geteuid() != 0 or os.readlink('/proc/self/ns/net') == os.readlink('/proc/1/ns/net'):
        raise SystemExit('Run with sudo unshare --net in a separate network namespace')
    binary, output = Path(args.binary), Path(args.output)
    binary, output = binary.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True)

    class DelayedResponse(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(float(self.path.strip('/')))
            body = b'{"ok": true}'
            try:
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                pass  # The stock proxy disconnects before this reply.

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), DelayedResponse)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    upstream_port = server.server_port
    results = []
    try:
        for name, timeout, delay in [('stock-short', None, 1), ('stock-long', None, 18),
                                     ('fixed-long', '3600s', 18)]:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                proxy_port = sock.getsockname()[1]
            config = {'services': [{'name': 'transparent-egress', 'addr': f'127.0.0.1:{proxy_port}',
                'bypass': 'allowlist', 'handler': {'type': 'red', 'metadata': {
                    'sniffing': True, 'sniffing.timeout': '5s', 'sniffing.fallback': True,
                    **({'readTimeout': timeout} if timeout else {})}}, 'listener': {'type': 'red'}}],
                'bypasses': [{'name': 'allowlist', 'whitelist': True, 'matchers': ['localhost']}]}
            path = output/(name+'.json')
            path.write_text(json.dumps(config, indent=2)+'\n')
            rule = ['OUTPUT', '-p', 'tcp', '--dport', str(upstream_port), '-m', 'owner',
                    '--uid-owner', '65534', '-j', 'REDIRECT', '--to-ports', str(proxy_port)]
            subprocess.run(['iptables', '-t', 'nat', '-A', *rule], check=True)
            with (output/(name+'.log')).open('w') as log:
                proxy = subprocess.Popen([str(binary), '-C', str(path)], stdout=log, stderr=subprocess.STDOUT)
                try:
                    time.sleep(.5)
                    if proxy.poll() is not None:
                        raise RuntimeError('GOST failed to start; inspect '+str(output/(name+'.log')))
                    code = '''import http.client,json,time,sys
started=time.monotonic()
try:
 c=http.client.HTTPConnection('127.0.0.1',int(sys.argv[1]),timeout=30)
 c.request('GET','/'+sys.argv[2],headers={'Host':'localhost'})
 response=c.getresponse();body=response.read()
 result={'status':response.status,'body':body.decode()}
except Exception as exc:
 result={'exception':type(exc).__name__,'message':str(exc)}
result['elapsed']=time.monotonic()-started
print(json.dumps(result))
'''
                    result = subprocess.run(['/usr/bin/python3', '-c', code, str(upstream_port), str(delay)],
                        check=True, capture_output=True, text=True, user=65534, group=65534)
                    row = {'case': name, **json.loads(result.stdout)}
                    results.append(row)
                    print(json.dumps(row), flush=True)
                finally:
                    proxy.terminate()
                    proxy.wait(timeout=10)
                    subprocess.run(['iptables', '-t', 'nat', '-D', *rule], check=True)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    (output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
    assert results[0].get('status') == 200
    assert results[1].get('exception') == 'RemoteDisconnected'
    assert 14 <= results[1]['elapsed'] <= 17
    assert results[2].get('status') == 200 and results[2]['elapsed'] >= 18


if __name__ == '__main__':
    main()
