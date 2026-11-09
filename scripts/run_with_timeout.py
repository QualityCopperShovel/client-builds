#!/usr/bin/env python3
"""POSIX command deadline, including descendants that retain output pipes."""
import os
import signal
import subprocess
import sys
import time


def main():
    seconds = float(sys.argv[1])
    if seconds <= 0:
        raise SystemExit('SECONDS must be positive')
    child = subprocess.Popen(sys.argv[2:], start_new_session=True)
    started = time.monotonic()
    def kill_group():
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    def interrupted(signum, _frame):
        kill_group()
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        result = child.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        print(f'Timed out after {seconds}s: {sys.argv[2]}', file=sys.stderr, flush=True)
        result = 124
    finally:
        # Also close descendant-held pipes when the immediate parent exits first.
        kill_group()
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        print('Child did not reap within 2s after SIGKILL', file=sys.stderr, flush=True)
    print(f'command terminal exit={result} elapsed={time.monotonic()-started:.3f}s', file=sys.stderr, flush=True)
    return result if result >= 0 else 128 - result


if __name__ == '__main__':
    sys.exit(main())
