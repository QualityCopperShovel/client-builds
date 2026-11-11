#!/usr/bin/env python3
"""One bounded, content-free snapshot after a failed simulator startup stage."""
# @lat: [[ios-runner#Installer failure evidence]]
import argparse
import json
import math
import os
import re
import selectors
import signal
import subprocess
import time
from pathlib import Path

MAX_BYTES = 262144
PROCESSES = {'xcrun', 'simctl', 'installd', 'installcoordinationd', 'CoreSimulatorService',
             'com.apple.CoreSimulator.CoreSimulatorService', 'simulatord', 'SimulatorTrampoline',
             'launchd_sim', 'Simulator', 'ExcessiveCode', 'runningboardd', 'SpringBoard', 'backboardd'}
DOMAINS = ('MIInstallerErrorDomain', 'IXErrorDomain', 'NSPOSIXErrorDomain', 'NSCocoaErrorDomain',
           'FBSOpenApplicationServiceErrorDomain', 'SimError', 'LSApplicationWorkspaceErrorDomain')
FLAGS = {'timeout': r'timed? out|timeout', 'disk_full': r'no space|ENOSPC',
         'permission': r'permission|EPERM|EACCES', 'signing': r'codesign|code signing|signature',
         'unresponsive': r'deadlock|unresponsive|hung', 'install_failed': r'failed to install|installation failed',
         'launch_failed': r'failed to launch|failed to open|launch failed'}


def collect(command, end, cap):
    stop = min(end, time.monotonic() + cap)
    if stop <= time.monotonic():
        return {'state': 'timed_out', 'reason': 'budget_exhausted'}, b''
    started = time.monotonic()
    process = None
    output = bytearray()
    state, reason = 'completed', None
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                left = stop - time.monotonic()
                if left <= 0:
                    state, reason = 'timed_out', 'command_deadline'
                    break
                for key, _ in selector.select(min(left, .05)):
                    chunk = os.read(key.fileobj.fileno(), min(16384, MAX_BYTES-len(output)))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                    if len(output) >= MAX_BYTES:
                        state, reason = 'partial', 'output_bound'
                        break
                if reason:
                    break
        if process.poll() is None and reason is None:
            try:
                process.wait(timeout=max(.001, stop-time.monotonic()))
            except subprocess.TimeoutExpired:
                state, reason = 'timed_out', 'command_deadline'
    except OSError:
        state, reason = 'failed', 'command_unavailable'
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=.1)
            except subprocess.TimeoutExpired:
                pass
        if process is not None and process.stdout is not None:
            process.stdout.close()
    code = process.returncode if process is not None else None
    if state == 'completed' and code != 0:
        state, reason = 'failed', 'command_exit'
    meta = {'state': state, 'elapsed_ms': round((time.monotonic()-started)*1000),
            'exit_code': code, 'bytes_examined': len(output)}
    if reason:
        meta['reason'] = reason
    return meta, bytes(output)


def service_errors(raw):
    # Decode only complete JSON records. Raw messages never reach disk or artifacts.
    text = raw.decode('utf-8', errors='replace')
    decoder = json.JSONDecoder()
    records, index = [], 0
    while index < len(text) and len(records) < 100:
        while index < len(text) and text[index] in ' \n\r\t[,':
            index += 1
        if index >= len(text) or text[index] == ']':
            break
        try:
            row, index = decoder.raw_decode(text, index)
        except ValueError:
            break
        if not isinstance(row, dict):
            continue
        process = str(row.get('processImagePath') or row.get('process') or '').rsplit('/', 1)[-1]
        if process not in PROCESSES:
            continue
        message = str(row.get('eventMessage') or '')
        codes = []
        for domain in DOMAINS:
            for match in re.finditer(re.escape(domain) + r'[^\n]{0,24}?\bCode[=: ]+(-?\d{1,10})', message):
                value = int(match.group(1))
                if -(2**31) <= value < 2**31:
                    codes.append({'domain': domain, 'code': value})
        item = {'process': process, 'errors': codes[:8],
                'message_flags': [name for name, pattern in FLAGS.items() if re.search(pattern, message, re.I)]}
        kind = row.get('messageType')
        if kind in ('Error', 'Fault', 'error', 'fault', 16, 17):
            item['message_type'] = kind
        records.append(item)
    return records


def process_state(raw):
    rows = []
    for line in raw.decode('utf-8', errors='replace').splitlines():
        parts = line.split(None, 5)
        if len(parts) != 6:
            continue
        name = parts[5].rsplit('/', 1)[-1]
        if name not in PROCESSES or not re.fullmatch(r'[A-Za-z+<>?]{1,12}', parts[2]):
            continue
        try:
            pid, parent, cpu, rss = int(parts[0]), int(parts[1]), float(parts[3]), int(parts[4])
        except ValueError:
            continue
        if min(pid, parent, rss) < 0 or not math.isfinite(cpu):
            continue
        rows.append({'process': name, 'pid': pid, 'ppid': parent, 'state': parts[2], 'cpu_percent': cpu, 'rss_kb': rss})
    return rows[:32]


def resources(raw):
    values = {}
    for line in raw.decode('utf-8', errors='replace').splitlines():
        match = re.fullmatch(r'([A-Za-z _-]{1,60}):\s*(\d+)\.?', line.strip())
        if match:
            values[match[1].lower().replace(' ', '_')] = int(match[2])
    return dict(list(values.items())[:32])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('install', 'launch'), default='install')
    parser.add_argument('--device', required=True)
    parser.add_argument('--startup-deadline', required=True, type=float)
    parser.add_argument('--session-deadline', required=True, type=float)
    parser.add_argument('--output', required=True)
    parser.add_argument('--startup-log', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Fa-f0-9-]{36}', args.device) or not all(math.isfinite(v) for v in (args.startup_deadline, args.session_deadline)):
        parser.error('Valid device and finite existing deadlines required')
    began = time.monotonic()
    # Reserve cleanup/file-write margin inside both original deadlines, never renew them.
    end = min(began+15, args.startup_deadline, began+max(0, args.session_deadline-time.time()))-.25
    report = {'schema': 1, 'stage':args.stage, 'state': 'running', 'budget_seconds': round(max(0,end-began),3),
              'limits': {'bytes_per_command': MAX_BYTES, 'service_events_per_command': 100, 'process_rows': 32}, 'steps': {}}

    def trace(state):
        with open(args.startup_log, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps({'step':args.stage+'_evidence', 'state':state,
                                     'elapsed_ms':round((time.monotonic()-began)*1000), 'at':time.time()})+'\n')

    trace('running')
    commands = [
        ('processes', ['/bin/ps','-axo','pid=,ppid=,state=,pcpu=,rss=,comm='], 2, process_state),
        ('memory', ['/usr/bin/vm_stat'], 1, resources),
        ('disk', ['/bin/df','-Pk','/'], 1, lambda raw: disk_state(raw)),
        (args.stage, ['xcrun','simctl','spawn',args.device,'log','show','--last','3m','--style','json','--predicate',
            ('(process == "ExcessiveCode" OR process == "runningboardd" OR process == "SpringBoard" OR process == "backboardd")' if args.stage == 'launch'
             else '(process == "installd" OR process == "installcoordinationd")') + ' AND (messageType == 16 OR messageType == 17)'], 6, service_errors),
        ('core_simulator', ['/usr/bin/log','show','--last','3m','--style','json','--predicate',
                            '(subsystem BEGINSWITH "com.apple.CoreSimulator" OR process == "CoreSimulatorService" OR process == "com.apple.CoreSimulator.CoreSimulatorService" OR process == "simulatord" OR process == "SimulatorTrampoline") AND (messageType == 16 OR messageType == 17)'], 5, service_errors)]
    try:
        for name, command, cap, sanitize in commands:
            meta, raw = collect(command, end, cap)
            report['steps'][name] = {**meta, 'data':sanitize(raw)}
        states = {row['state'] for row in report['steps'].values()}
        report['state'] = 'completed' if states == {'completed'} else 'timed_out' if time.monotonic() >= end else 'partial'
    except Exception:
        report['state'] = 'failed'
        report['reason'] = 'capture_failed'
    finally:
        report['elapsed_ms'] = round((time.monotonic()-began)*1000)
        Path(args.output).write_text(json.dumps(report, sort_keys=True, indent=2)+'\n', encoding='utf-8')
        trace(report['state'])


def disk_state(raw):
    for line in reversed(raw.decode('utf-8', errors='replace').splitlines()):
        values = line.split()
        if len(values) >= 5 and all(v.isdecimal() for v in values[1:4]):
            return {'total_kb':int(values[1]), 'used_kb':int(values[2]), 'available_kb':int(values[3])}
    return {}


if __name__ == '__main__':
    main()
