#!/usr/bin/env python3
"""Trial overlapping simulator discovery, without booting during compilation."""
from pathlib import Path

path = Path('launch_check.py')
source = path.read_text()
begin = source.index('        # Cold simulator boot consumed')
end = source.index('        # Hosted runners provide unused devices.', begin)
source = source[:begin] + '''        # Only discovery overlaps compilation; boot still waits for the compiler.
        compile_done = threading.Event()
        runtime = 'com.apple.CoreSimulator.SimRuntime.iOS-18-6'
        def discover():
            runtimes = json.loads(run('xcrun', 'simctl', 'list', 'runtimes', '-j', timeout=120))['runtimes']
            if not any(r['identifier'] == runtime and r.get('isAvailable') for r in runtimes):
                raise RuntimeError('The proven iOS 18.6 simulator runtime is missing')
            return json.loads(run('xcrun', 'simctl', 'list', 'devices', 'available', '-j'))['devices']
        def delayed_discovery():
            if compile_done.wait(30):
                return None
            return discover()
        evidence['step'] = 'simulator compilation'
        run('python3', 'generate_project.py')
        with ThreadPoolExecutor(max_workers=1) as setup:
            discovery = setup.submit(delayed_discovery)
            try:
                run('xcodebuild', '-project', 'ExcessiveCode.xcodeproj', '-scheme', 'ExcessiveCode',
                    '-configuration', 'Debug', '-destination', 'generic/platform=iOS Simulator',
                    '-derivedDataPath', 'build/launch-check', 'ONLY_ACTIVE_ARCH=YES', 'ARCHS='+platform.machine(),
                    'CODE_SIGNING_ALLOWED=YES', 'CODE_SIGN_IDENTITY=-', 'build', timeout=480)
            finally:
                compile_done.set()
            devices = discovery.result()
        evidence['step'] = 'simulator boot'
        if devices is None:
            devices = discover()
''' + source[end:]
path.write_text(source)
