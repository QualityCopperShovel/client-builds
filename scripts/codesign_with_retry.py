#!/usr/bin/env python3
"""Retry only Apple's transient timestamp outage, preserving already-built artifacts."""
import subprocess
import sys
import time


def sign(arguments, *, run=subprocess.run, clock=time.monotonic, sleep=time.sleep,
         deadline_seconds=60, attempt_seconds=20, delays=(3, 6)):
    deadline = clock() + deadline_seconds
    for attempt in range(len(delays) + 1):
        remaining = deadline - clock()
        if remaining <= 0:
            print('codesign timed out: 60-second signing deadline exhausted', file=sys.stderr)
            return 124
        try:
            result = run(['codesign', *arguments], capture_output=True, text=True,
                         timeout=min(attempt_seconds, remaining), check=False)
        except subprocess.TimeoutExpired:
            print('codesign timed out; release stopped at signing', file=sys.stderr)
            return 124
        print(result.stdout, end='')
        print(result.stderr, end='', file=sys.stderr)
        if result.returncode == 0:
            return 0
        if 'The timestamp service is not available.' not in result.stderr or attempt == len(delays):
            return result.returncode
        remaining = deadline - clock()
        delay = delays[attempt]
        if remaining <= delay:
            print('codesign timed out before timestamp retry', file=sys.stderr)
            return 124
        print(f'Apple timestamp service unavailable; retry {attempt + 2} in {delay}s', file=sys.stderr)
        sleep(delay)
    raise AssertionError('Unreachable signing state')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('usage: codesign_with_retry.py CODESIGN_ARGUMENTS...')
    raise SystemExit(sign(sys.argv[1:]))
