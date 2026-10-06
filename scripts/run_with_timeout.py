#!/usr/bin/env python3
"""Run one release command with an explicit overall deadline."""

import subprocess
import sys


def main():
    if len(sys.argv) < 3:
        raise SystemExit('usage: run_with_timeout.py SECONDS COMMAND [ARG ...]')
    seconds = int(sys.argv[1])
    if seconds <= 0:
        raise SystemExit('SECONDS must be positive')
    try:
        completed = subprocess.run(sys.argv[2:], timeout=seconds, check=False)
    except subprocess.TimeoutExpired:
        print(f'Timed out after {seconds}s: {sys.argv[2]}', file=sys.stderr)
        raise SystemExit(124)
    raise SystemExit(completed.returncode)


if __name__ == '__main__':
    main()
