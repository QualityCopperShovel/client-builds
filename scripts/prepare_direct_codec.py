"""Prepare an isolated executable from a verified private source snapshot."""
import hashlib
import json
from pathlib import Path

root = Path('native-client')
source = (root / 'Shared/Voice/VoiceRecorder.swift').read_text()
marker = 'final class VoiceWindow {'
if source.count(marker) != 1:
    raise SystemExit('Expected one VoiceWindow declaration')
start = source.index(marker)
end = source.index('\n}\n', start) + 2
window = source[start:end]
out = Path('codec-evidence')
out.mkdir(exist_ok=True)
Path('probe-window.swift').write_text('import AVFoundation\nimport Foundation\n' + window + '\n')
plan = {'mode': 'direct-synchronous-executable', 'source_receipt': Path('source-receipt.txt').read_text(),
        'window_sha256': hashlib.sha256(window.encode()).hexdigest(),
        'fixture_sha256': hashlib.sha256((root / 'CodecProbe/DirectCodecProbe.swift').read_bytes()).hexdigest(),
        'case_deadline_seconds': 8, 'cases': 12, 'network': False, 'microphone': False,
        'old_run': 42620733298, 'old_hang_cause': 'unknown'}
(out / 'probe-plan.json').write_text(json.dumps(plan, indent=2))
print(json.dumps(plan), flush=True)
