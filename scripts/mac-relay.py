#!/usr/bin/env python3
"""Let an agent drive Excessive Code for Mac on a hosted Mac's screen over HTTP.

Runs on the hosted runner (mac-app-session.yml), behind a Cloudflare quick tunnel.
Every request needs `Authorization: Bearer <token>`; the token reaches the agent only inside
the encrypted handoff artifact, never in logs. Screenshots use `screencapture -x`; clicks,
typing and keys use cliclick. Coordinates are screen points, which match the pixels of /shot
images (screenshots are scaled from display pixels to points).

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
APP = os.environ['APP_PATH']
PROCESS = os.environ.get('APP_PROCESS', 'FairyStackCompanion')
DOMAIN = os.environ.get('APP_DEFAULTS', 'com.fairystack.companion')
IDLE = int(os.environ.get('IDLE_SECONDS', '900'))
DEADLINE = float(os.environ['DEADLINE'])
PORT = int(os.environ.get('RELAY_PORT', '8765'))
LOG = open(os.environ.get('RELAY_LOG', 'evidence/relay.log'), 'a', buffering=1)
last_request = time.time()
lock = threading.Lock()  # one screen: run actions one at a time


def run(cmd, timeout=60, env=None):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return {'exit_code': p.returncode, 'stdout': p.stdout[-20000:], 'stderr': p.stderr[-4000:]}


def osascript(script, timeout=60):
    return run(['osascript', '-e', script], timeout=timeout)


_points = None


def points():
    """Main display size in points (cliclick's coordinate space)."""
    global _points
    if _points is None:
        r = osascript('tell application "Finder" to get bounds of window of desktop', timeout=20)
        parts = [int(x) for x in r['stdout'].replace(',', ' ').split()] if not r['exit_code'] else []
        if len(parts) != 4:
            raise RuntimeError('display size unknown: ' + (r['stderr'] or r['stdout'])[:300])
        _points = (parts[2] - parts[0], parts[3] - parts[1])
    return _points


def shot():
    with tempfile.TemporaryDirectory() as d:
        png, jpg = os.path.join(d, 's.png'), os.path.join(d, 's.jpg')
        r = run(['screencapture', '-x', '-m', '-t', 'png', png], timeout=30)
        if r['exit_code'] or not os.path.exists(png):
            raise RuntimeError(r['stderr'] or 'screenshot failed')
        w, h = points()
        r = run(['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', '80', '-z', str(h), str(w), png, '--out', jpg], timeout=30)
        if r['exit_code']:
            raise RuntimeError(r['stderr'] or 'resize failed')
        return open(jpg, 'rb').read()


def ui():
    """Windows of the app with their controls (names, roles, positions, sizes) from System Events."""
    script = f'''
on xy(p)
  return ((item 1 of p) as text) & "," & ((item 2 of p) as text)
end xy
set out to ""
tell application "System Events"
  if not (exists process "{PROCESS}") then return "app not running"
  tell process "{PROCESS}"
    repeat with w in windows
      set out to out & "window " & (name of w as text) & " at " & my xy(position of w) & " size " & my xy(size of w) & linefeed
      repeat with e in (UI elements of w)
        try
          set out to out & "  " & (role of e as text) & " " & (description of e as text) & " at " & my xy(position of e) & " size " & my xy(size of e) & linefeed
        end try
      end repeat
    end repeat
  end tell
end tell
return out'''
    return osascript(script, timeout=60)


def launch(body):
    """Quit and reopen the app; `reset` clears its saved windows and stacks first."""
    run(['pkill', '-x', PROCESS], timeout=10)
    for _ in range(50):
        if run(['pgrep', '-x', PROCESS], timeout=5)['exit_code']:
            break
        time.sleep(0.2)
    if body.get('reset'):
        run(['defaults', 'delete', DOMAIN], timeout=20)
    args = [str(a) for a in body.get('args', [])]
    return run(['open', '-n', APP, *(['--args', *args] if args else [])], timeout=60)


def crashes():
    """The app's crash reports on this runner: name and first lines of each, newest first."""
    found = []
    for d in ('~/Library/Logs/DiagnosticReports', '/Library/Logs/DiagnosticReports'):
        d = os.path.expanduser(d)
        for name in (os.listdir(d) if os.path.isdir(d) else []):
            if name.startswith(PROCESS) and name.endswith(('.ips', '.crash')):
                path = os.path.join(d, name)
                with open(path, errors='replace') as f:
                    head = f.read(4000)
                found.append({'name': name, 'mtime': os.path.getmtime(path), 'head': head})
    found.sort(key=lambda c: -c['mtime'])
    return {'exit_code': 0, 'crashes': found[:10]}


def click(body, kind='c'):
    x, y = int(round(float(body['x']))), int(round(float(body['y'])))
    return run(['cliclick', '-r', f'{kind}:{x},{y}'], timeout=30)


def action(path, body):
    if path == '/click':
        return click(body, {'double': 'dc', 'right': 'rc'}.get(body.get('kind'), 'c'))
    if path == '/move':
        return click(body, 'm')
    if path == '/drag':
        return run(['cliclick', '-r', f'dd:{int(body["x1"])},{int(body["y1"])}', f'dm:{int(body["x2"])},{int(body["y2"])}',
                    f'du:{int(body["x2"])},{int(body["y2"])}'], timeout=30)
    if path == '/scroll':
        # Positive dy scrolls content down; cliclick has no wheel, so use a CGEvent through JXA.
        dy = int(body.get('dy', 5))
        if 'x' in body:
            click(body, 'm')
        js = ('ObjC.import("CoreGraphics");'
              f'var e=$.CGEventCreateScrollWheelEvent(null,0,1,{-dy});$.CGEventPost(0,e);')
        return run(['osascript', '-l', 'JavaScript', '-e', js], timeout=20)
    if path == '/type':
        return run(['cliclick', '-r', 't:' + str(body['text'])], timeout=60)
    if path == '/key':
        # cliclick kp: names (return, esc, tab, arrow-up, ...) with optional modifiers (cmd, alt, ctrl, shift).
        mods = [m for m in body.get('mods', []) if m in ('cmd', 'alt', 'ctrl', 'shift', 'fn')]
        key = str(body['key'])
        if len(key) == 1:
            seq = [f'kd:{",".join(mods)}'] if mods else []
            seq += ['t:' + key] + ([f'ku:{",".join(mods)}'] if mods else [])
        else:
            seq = ([f'kd:{",".join(mods)}'] if mods else []) + [f'kp:{key}'] + ([f'ku:{",".join(mods)}'] if mods else [])
        return run(['cliclick', '-r', *seq], timeout=30)
    if path == '/ui':
        return ui()
    if path == '/launch':
        return launch(body)
    if path == '/open':
        return run(['open', '-a', APP, str(body['url'])], timeout=30)
    if path == '/appearance':
        dark = 'true' if body.get('dark') else 'false'
        return osascript(f'tell application "System Events" to tell appearance preferences to set dark mode to {dark}')
    if path == '/logs':
        secs = max(5, min(int(body.get('seconds', 60)), 900))
        return run(['log', 'show', '--last', f'{secs}s', '--style', 'compact', '--predicate',
                    f'process == "{PROCESS}" OR process == "com.apple.WebKit.WebContent"'], timeout=90)
    if path == '/crashes':
        return crashes()
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
LOG.write('ready display=%sx%s\n' % points())
server.serve_forever()
sys.exit(0)
