#!/usr/bin/env python3
"""Instrument one no-upload trial to retain the existing simulator evidence."""
from pathlib import Path

path = Path('launch_check.py')
source = path.read_text()
needle = "        if container:\n            if evidence['pings']:\n"
replacement = '''        if container:
            # Read the test-only page events and native diagnostic queue before
            # termination; don't change any launch or main-thread deadline.
            try:
                events = container / 'Library/Caches/launch-check-events.json'
                (ROOT / 'launch-trial-events.json').write_bytes(events.read_bytes())
                prefs = plistlib.loads((container / 'Library/Preferences/com.fairystack.ios.plist').read_bytes())
                diagnostics = json.loads(prefs.get('deviceDiagnostics.queue.v1', b'[]'))
                (ROOT / 'launch-trial-diagnostics.json').write_text(json.dumps(diagnostics, indent=2))
            except (OSError, ValueError, TypeError):
                pass
            if evidence['pings']:
'''
if source.count(needle) != 1:
    raise SystemExit('Unexpected launch check source; no diagnostic trial run')
path.write_text(source.replace(needle, replacement))
