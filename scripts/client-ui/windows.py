"""Published Windows binary, UI Automation, real input and isolated HTTPS.
No debugger or production testing hook; ephemeral TLS trust exists only on CI.
"""
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import ssl
import subprocess
import threading
import time
import urllib.request
import winreg
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pywinauto import Application
import win32clipboard
import win32gui

OUT = Path('evidence')
OUT.mkdir(exist_ok=True)
report = {'status': 'running', 'checks': [], 'physical_device': False}
requests = []
hang_seen = threading.Event()
HTML = '''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>FairyStack UI fixture</title>
<style>:root{background:#edf7f1;color:#17211c}body{font:20px system-ui;padding:32px}
@media(prefers-color-scheme:dark){:root{background:#141c18;color:#e6efe9}}
input{background:inherit;color:inherit;font:inherit}a{color:inherit}</style>
<h1>FairyStack UI fixture</h1><label>Draft <input aria-label="Draft" id="draft"></label>
<p>COOKIE_STATUS</p><p><a href="/hang">Never resolving page</a></p>'''


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        cookie = self.headers.get('Cookie', '')
        requests.append({'path': self.path, 'cookie_present': 'client_ui=stored' in cookie})
        if self.path == '/hang' and not hang_seen.is_set():
            hang_seen.set()
            time.sleep(75)
        body = HTML.replace('COOKIE_STATUS', 'Cookie persisted' if 'client_ui=stored' in cookie else 'First visit').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Set-Cookie', 'client_ui=stored; Max-Age=3600; Secure; SameSite=Strict; Path=/')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass

    def do_POST(self):
        self.send_error(405, 'Fixture accepts reads only')


def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def start_fixture():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Disposable client UI test')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
        .sign(key, hashes.SHA256()))
    folder = Path(os.environ['RUNNER_TEMP'])
    certfile, keyfile = folder/'client-ui-cert.pem', folder/'client-ui-key.pem'
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    # Current-user root installation opens a confirmation dialog. The disposable
    # hosted runner is already administrator; machine trust is noninteractive.
    subprocess.run(['certutil', '-f', '-addstore', 'Root', str(certfile)], check=True, timeout=15)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile, keyfile)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.socket.settimeout(15)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, cert.fingerprint(hashes.SHA1()).hex()


def theme(dark):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
        winreg.SetValueEx(key, 'AppsUseLightTheme', 0, winreg.REG_DWORD, 0 if dark else 1)


def connect(installed):
    app = Application(backend='uia').connect(path=str(installed), timeout=30)
    window = app.top_window()
    window.wait('visible', timeout=30)
    window.set_focus()
    window.child_window(title='Draft', control_type='Edit').wait('visible', timeout=30)
    return window


def main():
    window = server = thumbprint = None
    try:
        meta = json.loads(get('https://fairystack.com/assets/windows-version.json'))
        data = get(meta['download_url'])
        assert hashlib.sha256(data).hexdigest() == meta['download_sha256']
        (OUT/'release.json').write_text(json.dumps(meta, indent=2))
        server, thumbprint = start_fixture()
        origin = f'https://127.0.0.1:{server.server_port}/'
        setup = Path(os.environ['RUNNER_TEMP'])/'FairyStack-Setup.exe'
        setup.write_bytes(data)
        settings = Path(os.environ['LOCALAPPDATA'])/'FairyStack'
        settings.mkdir(exist_ok=True)
        (settings/'settings.json').write_text(json.dumps({'origin': origin, 'window_open': True}))
        theme(False)
        process = subprocess.Popen([str(setup)])
        assert process.wait(timeout=60) == 0
        installed = Path(os.environ['LOCALAPPDATA'])/'Programs/FairyStack/FairyStack.exe'
        assert hashlib.sha256(installed.read_bytes()).hexdigest() == meta['download_sha256']
        window = connect(installed)
        report['checks'].append('Published checksummed installer opened its native window with valid local TLS')
        window.capture_as_image().save(OUT/'windows-light.png')
        draft = window.child_window(title='Draft', control_type='Edit')
        draft.click_input()
        window.type_keys('A draft entered through Windows', with_spaces=True, pause=.03)
        assert draft.get_value() == 'A draft entered through Windows'
        window.type_keys('^a^c', pause=.1)
        win32clipboard.OpenClipboard()
        try:
            assert win32clipboard.GetClipboardData() == 'A draft entered through Windows'
        finally:
            win32clipboard.CloseClipboard()
        report['checks'].append('Real mouse focus, Windows typing and clipboard copy worked')
        bounds = window.rectangle()
        win32gui.MoveWindow(window.handle, bounds.left, bounds.top, 540, 620, True)
        time.sleep(.5)
        assert draft.get_value() == 'A draft entered through Windows'
        window.capture_as_image().save(OUT/'windows-small.png')
        report['checks'].append('Resizing the actual native window retained the draft')
        window.child_window(title='Never resolving page', control_type='Hyperlink').click_input()
        end = time.monotonic()+75
        while time.monotonic() < end:
            if 'could not load' in window.window_text().lower():
                break
            time.sleep(.5)
        else:
            raise AssertionError('Never-resolving navigation did not reach a visible error within 75 seconds')
        window.capture_as_image().save(OUT/'windows-timeout.png')
        window.child_window(title='Retry', control_type='Hyperlink').click_input()
        window.child_window(title='Draft', control_type='Edit').wait('visible', timeout=15)
        report['checks'].append('Never-resolving navigation reached the real 60-second error; Retry restored the page')
        window.close()
        subprocess.run(['taskkill', '/T', '/F', '/IM', 'FairyStack.exe'], timeout=15, capture_output=True)
        theme(True)
        saved = json.loads((settings/'settings.json').read_text())
        saved['window_open'] = True
        (settings/'settings.json').write_text(json.dumps(saved))
        restart_index = len(requests)
        subprocess.Popen([str(installed)])
        window = connect(installed)
        window.capture_as_image().save(OUT/'windows-dark.png')
        reopened = [x for x in requests[restart_index:] if x['path'] == '/workspace/']
        assert reopened and reopened[0]['cookie_present'], 'First document after process restart lost its persistent cookie'
        report['checks'].append('First document after process restart retained its persistent cookie; dark rendering captured')
        report.update(status='completed', version=meta['version'], limitations='Isolated HTTPS fixtures; prior run verified public sign-in rendering. No authenticated chat, real microphone, SmartScreen or Parallels/ARM compatibility exercised.')
    except BaseException as e:
        report.update(status='failed', error=str(e))
        if window:
            try:
                window.capture_as_image().save(OUT/'windows-failure.png')
                (OUT/'controls.txt').write_text('\n'.join(f'{x.element_info.control_type}: {x.window_text()}' for x in window.descendants()), encoding='utf-8')
            except Exception:
                pass
        raise
    finally:
        (OUT/'windows.json').write_text(json.dumps(report, indent=2))
        (OUT/'requests.json').write_text(json.dumps(requests, indent=2))
        subprocess.run(['taskkill', '/T', '/F', '/IM', 'FairyStack.exe'], timeout=15, capture_output=True)
        if server:
            server.shutdown()
            server.server_close()
        if thumbprint:
            subprocess.run(['certutil', '-delstore', 'Root', thumbprint], timeout=15, capture_output=True)


if __name__ == '__main__':
    main()
