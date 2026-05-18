"""
Local HTTP API server — light-control fallback when Firebase/internet is down.

Listens on 0.0.0.0:{port} and accepts:
    PUT /lights/{id}   body: {"state": true|false}  → toggle a named light
    GET /ping          → {"ok": true}  (reachability probe)

Commands are forwarded via the on_light_cmd callback, which the main
controller wires to _execute_light_cmd / _execute_porch_cmd / etc.
The server runs in a daemon thread so it stops automatically with the process.
"""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class LocalApiServer:
    def __init__(
        self,
        port: int,
        on_light_cmd: Callable[[str, bool], None],
        get_device_states: Optional[Callable[[], dict]] = None,
    ) -> None:
        self._port = port
        self._on_light_cmd = on_light_cmd
        self._get_device_states = get_device_states
        self._server: Optional[HTTPServer] = None

    def start(self) -> None:
        handler = self._make_handler(self._on_light_cmd, self._get_device_states)
        self._server = HTTPServer(('0.0.0.0', self._port), handler)
        threading.Thread(
            target=self._server.serve_forever,
            name='LocalApiServer',
            daemon=True,
        ).start()
        logger.info(f'Local API server listening on port {self._port}')

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()

    @staticmethod
    def _make_handler(
        on_light_cmd: Callable[[str, bool], None],
        get_device_states: Optional[Callable[[], dict]],
    ):
        class _Handler(BaseHTTPRequestHandler):

            def do_GET(self):
                path = self.path.rstrip('/')
                if path == '/ping':
                    self._reply(200, {'ok': True})
                elif path == '/devices':
                    if get_device_states is None:
                        self._reply(503, {'error': 'not available'})
                    else:
                        try:
                            self._reply(200, get_device_states())
                        except Exception as e:
                            logger.error(f'LocalAPI /devices error: {e}')
                            self._reply(500, {'error': str(e)})
                else:
                    self._reply(404, {'error': 'not found'})

            def do_PUT(self):
                parts = self.path.strip('/').split('/')
                if len(parts) != 2 or parts[0] != 'lights':
                    self._reply(400, {'error': 'use PUT /lights/{id}'})
                    return
                light_id = parts[1]
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    body = json.loads(self.rfile.read(length))
                    state = bool(body['state'])
                except Exception:
                    self._reply(400, {'error': 'body must be {"state": true|false}'})
                    return
                try:
                    on_light_cmd(light_id, state)
                    self._reply(200, {'ok': True})
                except Exception as e:
                    logger.error(f'LocalAPI handler error: {e}')
                    self._reply(500, {'error': str(e)})

            def _reply(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, fmt, *args):
                logger.debug('LocalAPI: ' + fmt % args)

        return _Handler
