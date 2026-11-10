#!/usr/bin/env python3
"""Prove the public relay is ready within the existing handoff deadlines."""
# @lat: [[ios-runner#Public relay handoff health]]
import argparse
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530}
TRANSIENT_CURL = {5, 6, 7, 18, 28, 35, 52, 55, 56}


def wait(log, output, session_deadline, startup_deadline, seconds=120):
    started = time.monotonic()
    end = min(started + seconds, startup_deadline,
              started + max(0, session_deadline - time.time())) - .25
    timing = os.environ.get('COMMAND_TIMING_LOG')
    Path(output).unlink(missing_ok=True)

    def trace(attempt, state, **fields):
        row = {'step': 'handoff_health_attempt', 'attempt': attempt, 'state': state,
               'at': time.time(), 'elapsed_ms': round((time.monotonic()-started)*1000), **fields}
        line = json.dumps(row, sort_keys=True)
        print(line, flush=True)
        if timing:
            with open(timing, 'a', encoding='utf-8') as handle:
                handle.write(line+'\n')

    attempt = 0
    while time.monotonic() < end:
        attempt += 1
        # Read a bounded tail. Never print the tunnel log, URL, response or token.
        try:
            with open(log, 'rb') as handle:
                handle.seek(0, 2)
                handle.seek(max(0, handle.tell()-65536))
                text = handle.read(65536).decode('utf-8', errors='replace')
        except FileNotFoundError:
            text = ''
        urls = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com\b', text)
        url = next((u for u in urls if u != 'https://api.trycloudflare.com'), None)
        if url is None:
            trace(attempt, 'pending', reason='address_unavailable')
        else:
            budget = min(5, max(0, end-time.monotonic()))
            if budget <= 0:
                break
            trace(attempt, 'running')
            try:
                result = subprocess.run(
                    ['curl', '-sS', '--max-time', str(budget), '--connect-timeout', str(budget),
                     '--max-filesize', '4096', '--doh-url', 'https://1.1.1.1/dns-query',
                     '--write-out', '\n%{http_code}', url+'/health'],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=budget)
                code = result.returncode
                body, _, status = result.stdout.rpartition(b'\n')
                status = int(status) if re.fullmatch(rb'\d{3}', status) else 0
            except subprocess.TimeoutExpired:
                code, status, body = 28, 0, b''
            except OSError:
                trace(attempt, 'failed', reason='curl_unavailable')
                return 127
            fields = {'http_status': status, 'curl_exit': code}
            if code == 0 and status == 200:
                try:
                    value = json.loads(body)
                except (ValueError, UnicodeDecodeError):
                    value = None
                if not isinstance(value, dict) or value.get('ok') is not True or value.get('deadline') != session_deadline:
                    trace(attempt, 'failed', reason='relay_contract', **fields)
                    return 1
                if time.monotonic() >= end:
                    break
                Path(output).write_text(url+'\n', encoding='utf-8')
                os.chmod(output, 0o600)
                trace(attempt, 'completed', **fields)
                return 0
            retry = (code == 0 and status in TRANSIENT_HTTP) or code in TRANSIENT_CURL
            trace(attempt, 'pending' if retry else 'failed', reason='transient_health' if retry else 'health_rejected', **fields)
            if not retry:
                return 1
        time.sleep(min(1, max(0, end-time.monotonic())))
    trace(attempt, 'timed_out', reason='handoff_deadline')
    return 124


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tunnel-log', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--session-deadline', type=float, required=True)
    args = parser.parse_args()
    startup = float(os.environ['COMMAND_DEADLINE_MONOTONIC'])
    if not all(math.isfinite(n) for n in (startup, args.session_deadline)):
        parser.error('finite existing deadlines required')
    raise SystemExit(wait(args.tunnel_log, args.output, args.session_deadline, startup))


if __name__ == '__main__':
    main()
