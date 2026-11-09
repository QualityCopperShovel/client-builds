"""One bounded process per synthetic case; regular files cannot retain pipes."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

out = Path('codec-evidence').resolve()
rows, results = [], []

def save(name, data):
    path = out / name
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2))
    temp.replace(path)

def trace(data):
    line = json.dumps({'time': time.time(), **data})
    with (out / 'owner-trace.jsonl').open('a') as file:
        file.write(line + '\n'); file.flush(); os.fsync(file.fileno())
    print(line, flush=True)

for rate in [16000, 44100, 48000]:
    for milliseconds in [19, 49, 50, 500]:
        count = int(rate * milliseconds / 1000 + 0.5)
        case = f'{rate}-{count}'
        directory = out / case
        directory.mkdir()
        started = time.monotonic()
        trace({'case': case, 'step': 'direct-executable', 'state': 'started'})
        with (directory / 'stdout.jsonl').open('w') as stdout, (directory / 'stderr.txt').open('w') as stderr:
            process = subprocess.Popen([str(Path('direct-codec-probe').resolve()), str(rate), str(count), str(directory)],
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            state = 'completed'
            try:
                code = process.wait(timeout=8)
                if code != 0:
                    state = 'failed'
            except subprocess.TimeoutExpired:
                state, code = 'timed_out', 124
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)
        result = {'case': case, 'state': state, 'exit': code, 'elapsed': time.monotonic() - started}
        events = []
        path = directory / 'probe-trace.jsonl'
        if path.exists():
            events = [json.loads(line) for line in path.read_text().splitlines()]
        result['last_started'] = next((e for e in reversed(events) if e['state'] == 'started'), None)
        result['last_completed'] = next((e for e in reversed(events) if e['state'] == 'completed'), None)
        if (directory / 'result.json').exists():
            rows.append(json.loads((directory / 'result.json').read_text()))
        results.append(result)
        save('apple-tiny-aac.partial.json', rows)
        save('direct-case-results.json', results)
        trace(result)
save('apple-tiny-aac.json', rows)
trace({'step': 'all-cases', 'state': 'completed', 'results': len(results), 'rows': len(rows)})
if len(rows) != 12 or any(r['state'] != 'completed' for r in results):
    raise SystemExit('Some codec cases failed or timed out; inspect retained trace and partial rows')
