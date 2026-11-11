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
import math
import uuid
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
SCALE = int(os.environ.get('SCREEN_SCALE', '3'))  # iPhone 16: 3 pixels per point
PORT = int(os.environ.get('RELAY_PORT', '8765'))
# The existing absolute deadline still applies while the build prepares handoff.
HANDOFF_FILE = os.environ.get('RELAY_HANDOFF_FILE')
LOG = open(os.environ.get('RELAY_LOG', 'evidence/relay.log'), 'a', buffering=1)
last_request = time.time()
lock = threading.Lock()  # one simulator: run actions one at a time


# @lat: [[ios-runner#Simulator request deadlines]]
request_owner = threading.local()


class RequestTimeout(TimeoutError):
    def __init__(self, step):
        self.step = step
        super().__init__(step)


def progress(step, state, code=None):
    request_owner.step = step
    row = {'request_id': getattr(request_owner, 'id', None), 'step': step, 'state': state}
    if hasattr(request_owner, 'started'):
        row['elapsed_ms'] = round((time.monotonic() - request_owner.started) * 1000)
    if code is not None:
        row['exit_code'] = code
    # Metadata only: never command arguments, output, environment or typed content.
    LOG.write(json.dumps(row, sort_keys=True) + '\n')


def remaining(maximum, step):
    budget = min(maximum, getattr(request_owner, 'deadline', float('inf')) - time.monotonic())
    if budget <= 0:
        raise RequestTimeout(step)
    return budget


def run(cmd, timeout=60, *, step='command', env=None):
    progress(step, 'running')
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=remaining(timeout, step), env=env)
    except subprocess.TimeoutExpired:
        progress(step, 'timed_out', 124)
        raise RequestTimeout(step) from None
    progress(step, 'completed' if p.returncode == 0 else 'failed', p.returncode)
    return {'exit_code': p.returncode, 'stdout': p.stdout[-2000000:], 'stderr': p.stderr[-4000:]}


# A stale simulator accessibility bridge fails every AXe read and tap with this, though the screen is fine.
STALE_BRIDGE = 'No translation object returned'


def axe(*args, timeout=60):
    r = run(['axe', *args, '--udid', UDID], timeout=timeout, step='axe_' + args[0].replace('-', '_'))
    if r['exit_code'] and STALE_BRIDGE in r['stderr'] + r['stdout']:
        # launchd restarts the bridge at once; retry once after it settles.
        run(['xcrun', 'simctl', 'spawn', UDID, 'launchctl', 'stop', 'com.apple.CoreSimulator.bridge'], timeout=20, step='bridge_restart')
        LOG.write('%s bridge restarted\n' % time.strftime('%H:%M:%S'))
        for _ in range(5):
            time.sleep(remaining(2, 'bridge_settle'))
            r = run(['axe', *args, '--udid', UDID], timeout=timeout, step='axe_' + args[0].replace('-', '_'))
            if not (r['exit_code'] and STALE_BRIDGE in r['stderr'] + r['stdout']):
                break
    return r


def shot():
    with tempfile.TemporaryDirectory() as d:
        png, jpg = os.path.join(d, 's.png'), os.path.join(d, 's.jpg')
        r = run(['xcrun', 'simctl', 'io', UDID, 'screenshot', png], timeout=30)
        if r['exit_code']:
            raise RuntimeError(r['stderr'] or 'screenshot failed')
        # Scale to points so image pixels are tap coordinates.
        size = run(['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', png], timeout=30)['stdout']
        px = dict(line.split(': ') for line in size.split('\n')[1:] if ': ' in line)
        w, h = int(px['  pixelWidth']) // SCALE, int(px['  pixelHeight']) // SCALE
        r = run(['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', '80', '-z', str(h), str(w), png, '--out', jpg], timeout=30)
        if r['exit_code']:
            raise RuntimeError(r['stderr'] or 'resize failed')
        return open(jpg, 'rb').read()


def launch(body):
    """Relaunch the app; `env` reaches it through simctl's SIMCTL_CHILD_ prefix."""
    args = [str(a) for a in body.get('args', [])]
    env = {**os.environ, **{'SIMCTL_CHILD_' + k: str(v) for k, v in (body.get('env') or {}).items()}}
    run(['xcrun', 'simctl', 'terminate', UDID, BUNDLE], timeout=20, step='app_terminate')
    return run(['xcrun', 'simctl', 'launch', UDID, BUNDLE, *args], timeout=60, env=env, step='app_launch')


# @lat: [[ios-runner#Hosted offline checks]]
OFFLINE_SHOTS = {}

def network_cycle(body):
    """Cut this disposable runner's network, cold-open, capture, restore.

    A detached watchdog restores the interface even if the relay dies. Nothing
    here runs on a connected personal device. Screenshots stay in private memory.
    """
    route = run(['/sbin/route', '-n', 'get', 'default'], timeout=10, step='default_interface')
    interface = next((line.split(':', 1)[1].strip() for line in route['stdout'].splitlines()
                      if line.strip().startswith('interface:')), '')
    if not interface.startswith('en') or not interface[2:].isdigit():
        raise ValueError('No ordinary hosted runner network interface')
    OFFLINE_SHOTS.clear()
    # subprocess timeout alone cannot undo an interface change after process death.
    watchdog = subprocess.Popen([sys.executable, '-c',
        'import subprocess,time,sys;time.sleep(100);subprocess.run(["sudo","-n","/sbin/ifconfig",sys.argv[1],"up"],timeout=10)',
        interface], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    result = {'interface': interface}
    began = time.monotonic()
    try:
        down = run(['sudo', '-n', '/sbin/ifconfig', interface, 'down'], timeout=10, step='network_down')
        if down['exit_code']:
            return down
        result['network_down'] = True
        time.sleep(remaining(3, 'offline_settle'))
        result['offline_probe'] = run(['/usr/bin/curl', '-I', '--connect-timeout', '2', '--max-time', '4',
                                      'https://simple-maps.jessald.excessivecode.com/'], timeout=6, step='offline_probe')
        result['launch'] = launch({'env': body.get('env', {})})
        time.sleep(remaining(12, 'offline_render'))
        OFFLINE_SHOTS['reopen'] = shot()
        result['ui_before_tap'] = axe('describe-ui', timeout=20)
        if 'x' in body and 'y' in body:
            result['tap'] = axe('tap', '-x', str(float(body['x'])), '-y', str(float(body['y'])), timeout=20)
            time.sleep(remaining(1, 'tap_settle'))
            OFFLINE_SHOTS['tap'] = shot()
            result['ui_after_tap'] = axe('describe-ui', timeout=20)
        result['offline_seconds'] = round(time.monotonic() - began, 1)
    finally:
        result['restore'] = run(['sudo', '-n', '/sbin/ifconfig', interface, 'up'], timeout=10, step='network_restore')
        if not result['restore']['exit_code']:
            watchdog.terminate()
        time.sleep(remaining(5, 'network_restore_settle'))
    return result


def action(path, body):
    if path == '/network-cycle':
        return network_cycle(body)
    if path == '/location':
        granted = run(['xcrun', 'simctl', 'privacy', UDID, 'grant', 'location', BUNDLE], timeout=20)
        if granted['exit_code']:
            return granted
        return run(['xcrun', 'simctl', 'location', UDID, 'set', str(body['latitude']) + ',' + str(body['longitude'])], timeout=20)
    if path == '/tap':
        if 'label' in body:
            return axe('tap', '--label', str(body['label']))
        if 'id' in body:
            return axe('tap', '--id', str(body['id']))
        return axe('tap', '-x', str(body['x']), '-y', str(body['y']))
    if path == '/doubletap':
        # Two 'tap' steps in one AXe batch land about 0.18 s apart on AXe 1.6.0, inside WebKit's
        # double-tap window; 'touch --down --up' steps land 0.8-2 s apart and never double-tap.
        tap = 'tap -x %s -y %s' % (float(body['x']), float(body['y']))
        gap = max(0.0, min(float(body.get('gap', 0)), 0.5))
        steps = [tap, 'sleep %s' % gap, tap] if gap else [tap, tap]
        return axe('batch', *[arg for step in steps for arg in ('--step', step)])
    if path == '/batch':
        # Ordered AXe steps (tap, touch, swipe, type, key, sleep ...) in one session, for timed gestures.
        steps = [str(step) for step in body['steps']][:50]
        return axe('batch', *[arg for step in steps for arg in ('--step', step)], timeout=120)
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
        started = time.monotonic()
        status = 500
        acquired = False
        request_owner.id = uuid.uuid4().hex
        request_owner.started = started
        request_owner.step = 'authenticate'
        try:
            if self.path == '/health':
                status = 200
                return self.reply(200, {'ok': True, 'deadline': DEADLINE})
            auth = self.headers.get('Authorization', '')
            if not hmac.compare_digest(auth, 'Bearer ' + TOKEN):
                status = 401
                return self.reply(401, {'error': 'unauthorized'})
            # Old callers get a budget shorter than their existing HTTP timeout.
            defaults = {'/ui': 30, '/tap': 30, '/swipe': 30, '/launch': 60, '/stop': 15,
                        '/batch': 150, '/logs': 120, '/network-cycle': 150}
            try:
                requested = float(self.headers.get('X-Simulator-Timeout-Seconds', defaults.get(self.path, 90)))
            except ValueError:
                requested = float('nan')
            if not math.isfinite(requested) or not 0 < requested <= 150:
                status = 400
                return self.reply(400, {'state':'failed', 'step':'request_budget', 'error':'invalid_timeout'})
            budget = min(max(0, requested - min(2, requested / 4)), max(0, DEADLINE - time.time()))
            request_owner.deadline = started + budget
            last_request = time.time()
            progress('request', 'running')
            n = int(self.headers.get('Content-Length') or 0)
            request_owner.step = 'request_body'
            self.connection.settimeout(remaining(5, 'request_body'))
            try:
                body = json.loads(self.rfile.read(n) or b'{}') if n else {}
            except TimeoutError:
                raise RequestTimeout('request_body') from None
            # Stop is cancellation, not another simulator action waiting behind a stuck AXe call.
            if self.path == '/stop':
                progress('request', 'completed')
                status = 200
                self.reply(200, {'stopping': True})
                threading.Thread(target=server.shutdown, daemon=True).start()
                return
            acquired = lock.acquire(timeout=remaining(150, 'waiting_for_simulator'))
            if not acquired:
                raise RequestTimeout('waiting_for_simulator')
            try:
                if self.path == '/saved-shot':
                    picture = OFFLINE_SHOTS[str(body['name'])]
                    progress('request', 'completed')
                    status = 200
                    return self.reply(200, picture, 'image/jpeg')
                if self.path == '/shot':
                    picture = shot()
                    progress('request', 'completed')
                    status = 200
                    return self.reply(200, picture, 'image/jpeg')
                result = action(self.path, body)
            except KeyError:
                status = 404
                return self.reply(404, {'error': 'unknown action'})
            status = 200
            progress('request', 'failed' if isinstance(result, dict) and result.get('exit_code') else 'completed')
            self.reply(200, result)
        except (BrokenPipeError, ConnectionResetError):
            status = 499
            progress('response_delivery', 'cancelled')
        except RequestTimeout as error:
            status = 504
            progress(error.step, 'timed_out', 124)
            self.reply(status, {'state':'timed_out', 'step':error.step, 'error':'deadline',
                                'request_id':request_owner.id,
                                'elapsed_ms':round((time.monotonic()-started)*1000)})
        except Exception as error:
            status = 502
            progress(getattr(request_owner, 'step', 'request'), 'failed')
            self.reply(status, {'state':'failed', 'step':getattr(request_owner, 'step', 'request'),
                                'error':type(error).__name__, 'request_id':request_owner.id})
        finally:
            if acquired:
                lock.release()
            LOG.write('%s %s %s %dms\n' % (time.strftime('%H:%M:%S'), self.path, status, (time.monotonic() - started) * 1000))
            request_owner.__dict__.clear()

    do_GET = do_POST = handle_any


# @lat: [[ios-runner#Interactive simulator startup]]
def watchdog():
    global last_request
    handed_off = HANDOFF_FILE is None
    while True:
        time.sleep(10)
        now = time.time()
        if not handed_off and os.path.exists(HANDOFF_FILE):
            handed_off = True
            last_request = now
            LOG.write('handoff idle_timer_armed\n')
        if now > DEADLINE or (handed_off and now - last_request > IDLE):
            LOG.write('exit reason=%s\n' % ('deadline' if now > DEADLINE else 'idle'))
            server.shutdown()
            return


server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
threading.Thread(target=watchdog, daemon=True).start()
LOG.write('ready udid=%s\n' % UDID)
server.serve_forever()
sys.exit(0)
