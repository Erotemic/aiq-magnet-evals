"""Local HTTP proxy fixture: publish model info, run a tool, then stop or overflow."""
import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


@contextlib.contextmanager
def proxy_server(*, model='local-context', key='local-proxy-fixture-key', overflow=True):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            ok = self.headers.get('Authorization') == f'Bearer {key}'
            if not ok:
                self.reply(401, {'error': {'message': 'wrong fixture key'}})
            return ok

        def do_GET(self):
            if not self.authorized():
                return
            path = urlsplit(self.path).path
            calls.append({'method': 'GET', 'path': path})
            if path.endswith('/model/info'):
                self.reply(200, {'data': [{'model_name': model,
                    'litellm_params': {'model': 'openai/custom-local',
                                      'api_base': 'http://upstream.invalid/v1'},
                    'model_info': {'max_input_tokens': 131072, 'max_output_tokens': 4096,
                                   'supports_reasoning': True,
                                   'reasoning_effort_levels': ['high']}}]})
            else:
                self.reply(200, {'info': {'aliases': {}, 'team_id': None}})

        def do_POST(self):
            if not self.authorized():
                return
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append({'method': 'POST', 'model': body['model'],
                          'reasoning_effort': body.get('reasoning_effort')})
            if any(m['role'] == 'tool' for m in body['messages']):
                if overflow:
                    self.reply(400, {'error': {'code': '400', 'type': None, 'param': None,
                        'message': "litellm.ContextWindowExceededError: This model's maximum "
                                   'context length is 131072 tokens. However, your prompt '
                                   'contains 131117 input tokens.'}})
                    return
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'call-submit', 'type': 'function',
                    'function': {'name': 'submit', 'arguments': '{"answer": "4"}'}}]}
                finish = 'tool_calls'
            else:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'call-local', 'type': 'function',
                    'function': {'name': 'double', 'arguments': '{"value": 2}'}}]}
                finish = 'tool_calls'
            self.reply(200, {'id': 'chat-local', 'object': 'chat.completion',
                'created': int(time.time()), 'model': model,
                'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
