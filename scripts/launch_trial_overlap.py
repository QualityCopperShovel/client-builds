#!/usr/bin/env python3
"""Trial a delayed simulator boot while preserving the full check."""
from pathlib import Path

path = Path('launch_check.py')
source = path.read_text()
begin = source.index('        # Cold simulator boot consumed')
end = source.index("        app = ROOT / 'build/launch-check/Build/Products/Debug-iphonesimulator/ExcessiveCode.app'", begin)
source = source[:begin] + '''        # Discover first; start boot only if the compiler is still busy after 60s.
        evidence['step'] = 'simulator discovery'
        runtimes = json.loads(run('xcrun', 'simctl', 'list', 'runtimes', '-j', timeout=120))['runtimes']
        runtime = 'com.apple.CoreSimulator.SimRuntime.iOS-18-6'
        if not any(r['identifier'] == runtime and r.get('isAvailable') for r in runtimes):
            raise RuntimeError('The proven iOS 18.6 simulator runtime is missing')
        devices = json.loads(run('xcrun', 'simctl', 'list', 'devices', 'available', '-j'))['devices']
        prepared = next((d for d in devices.get(runtime, [])
                         if d['name'] == 'iPhone 16' and d['state'] in ('Shutdown', 'Booted')), None)
        evidence['prepared_simulator'] = prepared is not None
        sim = prepared['udid'] if prepared else run('xcrun', 'simctl', 'create', 'Launch-check',
                'com.apple.CoreSimulator.SimDeviceType.iPhone-16', runtime)
        need_boot = not prepared or prepared['state'] != 'Booted'
        compile_done = threading.Event()
        def delayed_boot():
            if not need_boot or compile_done.wait(60):
                return False
            run('xcrun', 'simctl', 'boot', sim)
            return True
        evidence['step'] = 'simulator compilation'
        with ThreadPoolExecutor(max_workers=1) as setup:
            boot = setup.submit(delayed_boot)
            try:
                run('python3', 'generate_project.py')
                run('xcodebuild', '-project', 'ExcessiveCode.xcodeproj', '-scheme', 'ExcessiveCode',
                    '-configuration', 'Debug', '-destination', 'generic/platform=iOS Simulator',
                    '-derivedDataPath', 'build/launch-check', 'ONLY_ACTIVE_ARCH=YES', 'ARCHS='+platform.machine(),
                    'CODE_SIGNING_ALLOWED=YES', 'CODE_SIGN_IDENTITY=-', 'build', timeout=480)
            finally:
                compile_done.set()
            booted = boot.result()
        evidence['step'] = 'simulator boot'
        if need_boot and not booted:
            run('xcrun', 'simctl', 'boot', sim)
''' + source[end:]
path.write_text(source)
