#!/usr/bin/env python3
"""Let an agent drive one booted iPhone Simulator over HTTP, like a remote screen.

Runs on the hosted Mac runner (iphone-sim-session.yml), behind a Cloudflare quick tunnel.
Every request needs `Authorization: Bearer <token>`; the token reaches the agent only inside
the encrypted handoff artifact, never in logs. Taps, swipes and typing go through AXe
(https://github.com/cameroncooke/AXe); screenshots and launches through simctl.
Coordinates are simulator points, which match the pixels of /shot images.

Exits on POST /stop, after IDLE seconds without requests, or at DEADLINE (epoch seconds).
Writes a content-free request log (path, status, ms) to evidence/relay.log.
"""
import hmac
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ['RELAY_TOKEN']
UDID = os.environ['DEVICE']
BUNDLE = os.environ.get('APP_BUNDLE', 'com.fairystack.ios')
IDLE = int(os.environ.get('IDLE_SECONDS', '900'))
DEADLINE = float(os.environ['DEADLINE'])
PORT = int(os.environ.get('RELAY_PORT', '8765'))
LOG = open(os.environ.get('RELAY_LOG', 'evidence/relay.log'), 'a', buffering=1)
last_request = time.time()
lock = threading.Lock()  # one simulator: run actions one at a time


def run(cmd, timeout=60):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return {'exit_code': p.returncode, 'stdout': p.stdout[-20000:], 'stderr': p.stderr[-4000:]}


def axe(*args, timeout=60):
    return run(['axe', *args, '--udid', UDID], timeout=timeout)


def shot():
    with tempfile.TemporaryDirectory() as d:
        png, jpg = os.path.join(d, 's.png'), os.path.join(d, 's.jpg')
        r = run(['xcrun', 'simctl', 'io', UDID, 'screenshot', png], timeout=30)
        if r['exit_code']:
            raise RuntimeError(r['stderr'] or 'screenshot failed')
        # Scale to points so image pixels are tap coordinates.
        w, h = points()
        r = run(['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', '80', '-z', str(h), str(w), png, '--out', jpg], timeout=30)
        if r['exit_code']:
            raise RuntimeError(r['stderr'] or 'resize failed')
        return open(jpg, 'rb').read()


_points = None


def points():
    global _points
    if _points is None:
        tree = json.loads(axe('describe-ui')['stdout'] or '[]')
        frame = (tree[0] if isinstance(tree, list) and tree else tree).get('frame', {})
        _points = (int(frame.get('width') or 393), int(frame.get('height') or 852))
    return _points


def launch(body):
    """Relaunch the app; `env` reaches it through simctl's SIMCTL_CHILD_ prefix."""
    args = [str(a) for a in body.get('args', [])]
    env = {**os.environ, **{'SIMCTL_CHILD_' + k: str(v) for k, v in (body.get('env') or {}).items()}}
    run(['xcrun', 'simctl', 'terminate', UDID, BUNDLE], timeout=20)
    p = subprocess.run(['xcrun', 'simctl', 'launch', UDID, BUNDLE, *args], capture_output=True, text=True,
                       timeout=60, env=env)
    return {'exit_code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}


def action(path, body):
    if path == '/tap':
        if 'label' in body:
            return axe('tap', '--label', str(body['label']))
        if 'id' in body:
            return axe('tap', '--id', str(body['id']))
        return axe('tap', '-x', str(body['x']), '-y', str(body['y']))
    if path == '/swipe':
        return axe('swipe', '--start-x', str(body['x1']), '--start-y', str(body['y1']), '--end-x', str(body['x2']),
                   '--end-y', str(body['y2']), '--duration', str(body.get('duration', 0.3)))
    if path == '/type':
        return axe('type', str(body['text']))
    if path == '/key':
        return axe('key', str(body['keycode']))
    if path == '/button':
        return axe('button', str(body['name']))
    if path == '/ui':
        return axe('describe-ui')
    if path == '/launch':
        return launch(body)
    if path == '/url':
        return run(['xcrun', 'simctl', 'openurl', UDID, str(body['url'])], timeout=30)
    if path == '/appearance':
        return run(['xcrun', 'simctl', 'ui', UDID, 'appearance', 'dark' if body.get('dark') else 'light'], timeout=20)
    if path == '/logs':
        secs = max(5, min(int(body.get('seconds', 60)), 900))
        return run(['xcrun', 'simctl', 'spawn', UDID, 'log', 'show', '--last', f'{secs}s', '--style', 'compact',
                    '--predicate', 'process == "ExcessiveCode" OR process == "com.apple.WebKit.WebContent"'], timeout=60)
    raise KeyError(path)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, status, data, kind='application/json'):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def handle_any(self):
        global last_request
        started = time.time()
        status = 500
        try:
            if self.path == '/health':
                status = 200
                return self.reply(200, {'ok': True, 'deadline': DEADLINE})
            auth = self.headers.get('Authorization', '')
            if not hmac.compare_digest(auth, 'Bearer ' + TOKEN):
                status = 401
                return self.reply(401, {'error': 'unauthorized'})
            last_request = time.time()
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(n) or b'{}') if n else {}
            with lock:
                if self.path == '/shot':
                    status = 200
                    return self.reply(200, shot(), 'image/jpeg')
                if self.path == '/stop':
                    status = 200
                    self.reply(200, {'stopping': True})
                    threading.Thread(target=server.shutdown, daemon=True).start()
                    return
                try:
                    result = action(self.path, body)
                except KeyError:
                    status = 404
                    return self.reply(404, {'error': 'unknown action ' + self.path})
                status = 200
                self.reply(200, result)
        except (subprocess.TimeoutExpired, RuntimeError, ValueError, TypeError) as e:
            status = 502
            self.reply(502, {'error': type(e).__name__ + ': ' + str(e)[:500]})
        finally:
            LOG.write('%s %s %s %dms\n' % (time.strftime('%H:%M:%S'), self.path, status, (time.time() - started) * 1000))

    do_GET = do_POST = handle_any


def watchdog():
    while True:
        time.sleep(10)
        now = time.time()
        if now > DEADLINE or now - last_request > IDLE:
            LOG.write('exit reason=%s\n' % ('deadline' if now > DEADLINE else 'idle'))
            server.shutdown()
            return


server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
threading.Thread(target=watchdog, daemon=True).start()
LOG.write('ready udid=%s\n' % UDID)
server.serve_forever()
sys.exit(0)
