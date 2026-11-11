#!/usr/bin/env python3
"""Retry simulator infrastructure once; never turn missing evidence into a freeze."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def classify(code, result):
    if code == 0 and result.get('state') == 'completed':
        return 'passed'
    # Once the page has answered, any behavior failure must still block upload.
    if result.get('pings') or result.get('freeze'):
        return 'app_check_failed'
    step = result.get('step', '')
    if step in ('simulator discovery', 'simulator boot', 'simulator boot and installation',
                'simulator app process startup') or not result:
        return 'could_not_run'
    if step == 'simulator compilation' and any(
            c.get('state') in ('running', 'timed_out') for c in result.get('commands', [])):
        return 'could_not_run'
    return 'app_check_failed'


def main():
    root = Path.cwd()
    retained = root / 'launch-check-attempts'
    retained.mkdir(exist_ok=True)
    attempts = []
    limit = int(os.environ.get('EXCESSIVECODE_GATE_ATTEMPTS', '2'))
    if limit not in (1, 2):
        raise ValueError('Only one infrastructure retry is allowed')
    for attempt in range(1, limit + 1):
        for name in ('launch-check-result.json', 'launch-check-build.log'):
            (root / name).unlink(missing_ok=True)
        env = dict(os.environ)
        if attempt == 2:
            env['EXCESSIVECODE_GATE_STARTED_AT'] = str(time.time())
        process = subprocess.Popen([sys.executable, 'launch_check.py'], env=env,
                                   start_new_session=True)
        try:
            code = process.wait(timeout=735)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
            code = 124
        try:
            result = json.loads((root / 'launch-check-result.json').read_text())
        except (OSError, ValueError):
            result = {}
        outcome = classify(code, result)
        folder = retained / str(attempt)
        folder.mkdir(exist_ok=True)
        for name in ('launch-check-result.json', 'launch-check-build.log'):
            if (root / name).exists():
                shutil.copy2(root / name, folder / name)
        attempts.append({'attempt': attempt, 'outcome': outcome,
                         'step': result.get('step'), 'error': result.get('error'), 'exit_code': code})
        if outcome != 'could_not_run':
            break
        print('::warning::Check could not run: simulator/runner setup failed' +
              ('; retrying once.' if attempt < limit else '; no app-freeze verdict. Upload may proceed.'), flush=True)
    verdict = {'outcome': outcome, 'attempts': attempts}
    (root / 'launch-gate-result.json').write_text(json.dumps(verdict, indent=2)+'\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            label = {'passed': 'Launch check passed', 'could_not_run': 'Check could not run',
                     'app_check_failed': 'App launch check failed'}[outcome]
            f.write(f'### {label}\n\n{len(attempts)} attempt(s). See retained logs for each attempt.\n')
    return 1 if outcome == 'app_check_failed' else 0


if __name__ == '__main__':
    sys.exit(main())
