#!/usr/bin/env python3
"""Run one release command with an explicit overall deadline."""

import json
import math
import os
import re
import subprocess
import sys
import time


# @lat: [[ios-runner#Interactive simulator startup]]
def main():
    if len(sys.argv) < 3:
        raise SystemExit('usage: run_with_timeout.py SECONDS COMMAND [ARG ...]')
    seconds = int(sys.argv[1])
    if seconds <= 0:
        raise SystemExit('SECONDS must be positive')
    label = os.environ.get('COMMAND_LABEL')
    if label is not None and not re.fullmatch(r'[a-z][a-z0-9_]{0,48}', label):
        raise SystemExit('Invalid command label')
    limit = os.environ.get('COMMAND_DEADLINE_MONOTONIC')
    budget = seconds
    if limit is not None:
        limit = float(limit)
        if not math.isfinite(limit):
            raise SystemExit('Invalid command deadline')
        budget = min(seconds, max(0, limit - time.monotonic()))
    started = time.monotonic()

    def trace(state, code=None):
        if label is None:
            return
        row = {'step': label, 'state': state, 'elapsed_ms': round((time.monotonic() - started) * 1000),
               'at': time.time(), 'budget_seconds': round(budget, 3)}
        if code is not None:
            row['exit_code'] = code
        # Never write command arguments, paths, environment or subprocess output.
        line = json.dumps(row, sort_keys=True)
        print(line, file=sys.stderr, flush=True)
        if os.environ.get('COMMAND_TIMING_LOG'):
            with open(os.environ['COMMAND_TIMING_LOG'], 'a', encoding='utf-8') as handle:
                handle.write(line + '\n')

    trace('running')
    if budget <= 0:
        trace('timed_out', 124)
        raise SystemExit(124)
    try:
        completed = subprocess.run(sys.argv[2:], timeout=budget, check=False)
    except subprocess.TimeoutExpired:
        trace('timed_out', 124)
        print(f'Timed out after {budget:g}s: {sys.argv[2]}', file=sys.stderr)
        raise SystemExit(124)
    except OSError:
        trace('failed', 127)
        raise
    trace('completed' if completed.returncode == 0 else 'failed', completed.returncode)
    raise SystemExit(completed.returncode)


if __name__ == '__main__':
    main()
