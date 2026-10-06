"""Disposable emulator: canonical production code, ephemeral signer, native taps.
No production signing key or human session enters the runner.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

OUT = Path('evidence')
OUT.mkdir(exist_ok=True)
SDK = Path(os.environ['ANDROID_HOME'])
SOURCE = Path('client/native/android')
BT = SDK / 'build-tools/36.0.0'


def run(args, timeout=90, **kw):
    return subprocess.run([str(a) for a in args], timeout=timeout, check=True, **kw)


def adb(*args, **kw):
    return run([SDK / 'platform-tools/adb', *args], **kw)


def screenshot(name):
    with (OUT / (name + '.png')).open('wb') as f:
        adb('exec-out', 'screencap', '-p', stdout=f)


def nodes():
    adb('shell', 'uiautomator', 'dump', '/sdcard/ui.xml', stdout=subprocess.DEVNULL, timeout=15)
    xml = adb('shell', 'cat', '/sdcard/ui.xml', capture_output=True, text=True).stdout
    return ET.fromstring(xml).iter('node')


def tap(text, contains=False, limit=15, click=True):
    wanted = text.casefold()
    end = time.monotonic() + limit
    while time.monotonic() < end:
        for node in nodes():
            value = node.get('text', '').casefold()
            if (wanted in value if contains else wanted == value):
                x1, y1, x2, y2 = map(int, re.findall(r'\d+', node.get('bounds')))
                if click:
                    adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))
                return
        time.sleep(.3)
    raise AssertionError('Visible UI control not found: ' + text)


def prepare():
    # The workflow checked out and verified the private snapshot; only its identity is recorded.
    assert (SOURCE / 'build.py').is_file(), 'Android source snapshot is missing'
    (OUT / 'source.json').write_text(json.dumps({
        'revision': os.environ['SOURCE_REVISION'], 'snapshot': os.environ['SOURCE_COMMIT'],
        'signer': 'Ephemeral test identity; not the distributed release signer',
    }, indent=2))


def test():
    report = {'status': 'running', 'checks': [], 'physical_device': False}
    try:
        end = time.monotonic() + 240
        while time.monotonic() < end:
            r = subprocess.run([str(SDK/'platform-tools/adb'), 'shell', 'getprop', 'sys.boot_completed'], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip() == '1':
                break
            time.sleep(2)
        else:
            raise TimeoutError('Emulator failed to boot within 240 seconds')
        adb('shell', 'input', 'keyevent', '82')
        adb('shell', 'settings', 'put', 'global', 'window_animation_scale', '0')
        adb('shell', 'settings', 'put', 'global', 'transition_animation_scale', '0')
        adb('shell', 'settings', 'put', 'global', 'animator_duration_scale', '0')
        run(['python3', SOURCE/'build.py', '--sdk', SDK])
        key = Path('client-test.jks')
        run(['keytool', '-genkeypair', '-keystore', key, '-storepass', 'disposable', '-keypass', 'disposable', '-alias', 'test', '-dname', 'CN=Disposable UI Test', '-keyalg', 'RSA', '-validity', '1'])
        unsigned = next((SOURCE/'build').glob('*-unsigned.apk'))
        app = Path('client-test.apk')
        run([BT/'apksigner', 'sign', '--ks', key, '--ks-pass', 'pass:disposable', '--out', app, unsigned])
        b = Path('instrumentation-build')
        b.mkdir()
        (b/'classes').mkdir()
        (b/'dex').mkdir()
        jar = SDK/'platforms/android-36/android.jar'
        run([BT/'aapt2', 'link', '-I', jar, '--manifest', SOURCE/'instrumentation/AndroidManifest.xml', '-o', b/'resources.apk'])
        run(['javac', '-source', '8', '-target', '8', '-classpath', jar, '-d', b/'classes', *sorted((SOURCE/'instrumentation').rglob('*.java'))])
        run([BT/'d8', '--min-api', '26', '--lib', jar, '--output', b/'dex', *sorted((b/'classes').rglob('*.class'))])
        with zipfile.ZipFile(b/'resources.apk') as src, zipfile.ZipFile(b/'unsigned.apk', 'w') as dst:
            for n in src.namelist():
                dst.writestr(n, src.read(n))
            dst.write(b/'dex/classes.dex', 'classes.dex')
        run([BT/'zipalign', '-f', '4', b/'unsigned.apk', b/'aligned.apk'])
        run([BT/'apksigner', 'sign', '--ks', key, '--ks-pass', 'pass:disposable', '--out', b/'smoke.apk', b/'aligned.apk'])
        adb('install', '-r', app)
        adb('install', '-r', b/'smoke.apk')
        adb('logcat', '-c')
        # This existing instrumented runner blocks writes before exercising the
        # live workspace, then covers storage, file picker, consent and deadline.
        result = adb('shell', 'am', 'instrument', '-w', 'com.fairystack.android.tests/.Smoke', capture_output=True, text=True, timeout=180).stdout
        (OUT/'instrumentation.txt').write_text(result)
        if 'INSTRUMENTATION_CODE: -1' not in result or 'failure=' in result:
            raise AssertionError('Android instrumentation failed: ' + result)
        report['checks'].append('Production activity: storage, picker cancellation, microphone denial, timeout and retry')
        adb('shell', 'am', 'start', '-n', 'com.fairystack.android/.MainActivity')
        time.sleep(3)
        screenshot('android-light')
        tap('FairyStack ·', contains=True)
        tap('Add a FairyStack', contains=True, click=False)
        screenshot('android-server-menu')
        tap('Add a FairyStack', contains=True)
        tap('Cancel', click=False)
        screenshot('android-add-server')
        tap('Cancel')
        report['checks'].append('Native server menu and Add dialog opened with real coordinate taps; cancelled')
        adb('shell', 'cmd', 'uimode', 'night', 'yes')
        time.sleep(2)
        screenshot('android-dark')
        adb('shell', 'settings', 'put', 'system', 'accelerometer_rotation', '0')
        adb('shell', 'settings', 'put', 'system', 'user_rotation', '1')
        time.sleep(2)
        screenshot('android-landscape')
        report['checks'].append('Light, dark and landscape screenshots captured')
        report['status'] = 'completed'
    except BaseException as e:
        report.update(status='failed', error=str(e))
        try:
            screenshot('android-failure')
            state = adb('shell', 'dumpsys', 'activity', 'activities', capture_output=True, text=True).stdout
            (OUT/'activities.txt').write_text(state)
        except Exception:
            pass
        raise
    finally:
        (OUT/'android.json').write_text(json.dumps(report, indent=2))
        try:
            logs = adb('logcat', '-d', '-v', 'threadtime', 'chromium:V', 'ActivityTaskManager:I', 'AndroidRuntime:E', 'Instrumentation:I', '*:S', capture_output=True, text=True).stdout
            (OUT/'logcat.txt').write_text(logs)
        except Exception:
            pass


if __name__ == '__main__':
    {'prepare': prepare, 'test': test}[sys.argv[1]]()
