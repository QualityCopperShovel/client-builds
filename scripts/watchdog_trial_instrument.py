from pathlib import Path

path = Path('launch_check.py')
text = path.read_text()
old = "            if frozen['stuck_seconds'] < 5 or frozen['action'] != 'voice:flag':"
new = "            evidence['watchdog_observed_before_assertion'] = frozen\n" + old
assert text.count(old) == 1
text = text.replace(old, new)
old = "                    exists = (container / 'Library/Application Support/main-thread-freeze.json').exists()"
new = old + "\n" + '''                    evidence.setdefault('watchdog_queue_samples', []).append({
                        'at': time.time(), 'queue_count': len(rows),
                        'operations': [row.get('event', {}).get('operation') for row in rows],
                        'freeze_ids': [row.get('event', {}).get('id') for row in previous],
                        'freeze_file_exists': exists,
                    })'''
assert text.count(old) == 1
text = text.replace(old, new)
old = "    except Exception as error:\n        evidence.update(state='failed', error=str(error)[-3000:])"
new = "    except Exception as error:\n" + """        try:
            if container:
                events_path = container / 'Library/Caches/launch-check-events.json'
                evidence['fixture_events'] = json.loads(events_path.read_text())
        except (OSError, ValueError):
            pass
""" + "        evidence.update(state='failed', error=str(error)[-3000:])"
assert text.count(old) == 1
text = text.replace(old, new)
path.write_text(text)

# Capture evidence in the trial only. Sampling begins after simctl launch and
# stops before the deliberate watchdog injection; it never changes verdicts.
text = path.read_text()
old = "    command_lock = threading.Lock()\n"
new = old + '''    probe_stop = threading.Event()
    probe_thread = None
    probe_records = []
    def probe():
        started = time.monotonic()
        sampled = False
        while not probe_stop.is_set():
            record = {'at': time.time(), 'step': evidence.get('step'), 'pings': evidence.get('pings')}
            try:
                p = subprocess.run(['ps', '-axo', 'pid,ppid,pcpu,state,comm'], capture_output=True, text=True, timeout=3)
                record['processes'] = [line for line in p.stdout.splitlines() if any(x in line for x in ('ExcessiveCode.app/ExcessiveCode', 'CoreSimulator', 'SimulatorTrampoline', 'WebKit'))][:40]
                up = subprocess.run(['uptime'], capture_output=True, text=True, timeout=3)
                record['host_load'] = up.stdout.strip()
                age = time.monotonic() - evidence.get('last_ping', launched)
                if not sampled and time.monotonic()-started >= 8 and age >= 5:
                    candidates = [line for line in record['processes'] if 'ExcessiveCode.app/ExcessiveCode' in line]
                    if candidates:
                        pid = int(candidates[0].split()[0])
                        target = ROOT / ('launch-check-stack-' + str(int(time.time())) + '.txt')
                        result = subprocess.run(['sample', str(pid), '2', '-file', str(target)], capture_output=True, text=True, timeout=8)
                        record['stack'] = {'file': target.name, 'returncode': result.returncode, 'stderr': result.stderr[-1000:]}
                        if target.exists():
                            record['stack']['sample'] = target.read_text(errors='replace')[:120000]
                        sampled = True
            except Exception as error:
                record['probe_error'] = type(error).__name__ + ': ' + str(error)[:300]
            probe_records.append(record)
            probe_stop.wait(5)
'''
assert text.count(old) == 1
text = text.replace(old, new)
old = "        launched = time.monotonic()\n        seen = 0"
new = "        launched = time.monotonic()\n        probe_thread = threading.Thread(target=probe, daemon=True)\n        probe_thread.start()\n        seen = 0"
assert text.count(old) == 1
text = text.replace(old, new)
old = "                for value in rows[seen:]:\n"
new = old + "                    evidence.setdefault('timed_fixture_events', []).append({k: value[k] for k in ('observed_at', 'step', 'error', 'send_completed', 'completed', 'watchdog_ready') if k in value}) if not value.get('ping') else None\n"
assert text.count(old) == 1
text = text.replace(old, new)
old = "        # Stall injection/replay is an explicit diagnostic, not part of each release launch."
new = "        probe_stop.set()\n" + old
assert text.count(old) == 1
text = text.replace(old, new)
old = "    finally:\n        if sim:"
new = '''    finally:
        probe_stop.set()
        if probe_thread:
            probe_thread.join(timeout=9)
        evidence['host_probe'] = probe_records
        if container:
            try:
                prefs = plistlib.loads((container / 'Library/Preferences/com.fairystack.ios.plist').read_bytes())
                queue = json.loads(prefs.get('deviceDiagnostics.queue.v1', b'[]'))
                evidence['final_queue'] = [{'operation': row.get('event', {}).get('operation'), 'id': row.get('event', {}).get('id')} for row in queue]
            except Exception as error:
                evidence['final_queue_error'] = type(error).__name__ + ': ' + str(error)[:300]
            try:
                evidence['final_freeze'] = json.loads((container / 'Library/Application Support/main-thread-freeze.json').read_text())
            except Exception as error:
                evidence['final_freeze_error'] = type(error).__name__
        if sim:'''
assert text.count(old) == 1
text = text.replace(old, new)
path.write_text(text)

text = path.read_text()
old = "        command = {'argv': cmd, 'state': 'running'}"
new = "        command = {'argv': cmd, 'state': 'running', 'started_at': time.time()}"
assert text.count(old) == 1
text = text.replace(old, new)
old = "        command.update(state='completed' if process.returncode == 0 else 'failed', seconds=round(time.monotonic()-started, 2))"
new = "        command.update(ended_at=time.time(), state='completed' if process.returncode == 0 else 'failed', seconds=round(time.monotonic()-started, 2))"
assert text.count(old) == 1
text = text.replace(old, new)
old = "            command.update(state='timed_out', seconds=round(time.monotonic()-started, 2))"
new = "            command.update(ended_at=time.time(), state='timed_out', seconds=round(time.monotonic()-started, 2))"
assert text.count(old) == 1
text = text.replace(old, new)
path.write_text(text)

text = path.read_text()
old = "    command_lock = threading.Lock()\n"
new = old + '''    setup_probe_stop = threading.Event()
    setup_probe_records = []
    setup_probe_thread = None
    def setup_probe():
        sampled = False
        while not setup_probe_stop.is_set():
            with command_lock:
                running = [{'argv': list(c['argv'][:4]), 'started_at': c.get('started_at')} for c in evidence['commands'] if c.get('state') == 'running']
            row = {'at': time.time(), 'step': evidence.get('step'), 'running': running}
            try:
                ps = subprocess.run(['ps', '-axo', 'pid,ppid,pcpu,pmem,state,wchan,comm'], capture_output=True, text=True, timeout=4)
                row['ps_returncode'] = ps.returncode
                row['processes'] = [line for line in ps.stdout.splitlines() if any(x in line for x in ('CoreSimulator', 'simctl', 'SimulatorTrampoline', 'launchd_sim', 'SpringBoard'))][:80]
                row['ps_stderr'] = ps.stderr[-500:]
                up = subprocess.run(['uptime'], capture_output=True, text=True, timeout=3)
                row['host_load'] = up.stdout.strip()
                vm = subprocess.run(['vm_stat'], capture_output=True, text=True, timeout=3)
                row['vm_stat'] = vm.stdout[-2500:]
                delayed = any('get_app_container' in c['argv'] and c.get('started_at') and time.time()-c['started_at'] >= 12 for c in running)
                service = [line for line in row['processes'] if '/com.apple.CoreSimulator.CoreSimulatorService.xpc/Contents/MacOS/' in line]
                if delayed and service and not sampled:
                    pid = int(service[0].split()[0])
                    target = ROOT / ('setup-service-stack-' + str(int(time.time())) + '.txt')
                    result = subprocess.run(['sample', str(pid), '2', '-file', str(target)], capture_output=True, text=True, timeout=8)
                    row['service_stack'] = {'returncode': result.returncode, 'stderr': result.stderr[-1000:]}
                    if target.exists():
                        row['service_stack']['sample'] = target.read_text(errors='replace')[:120000]
                    sampled = True
            except Exception as error:
                row['probe_error'] = type(error).__name__ + ': ' + str(error)[:300]
            setup_probe_records.append(row)
            setup_probe_stop.wait(5)
'''
assert text.count(old) == 1
text = text.replace(old,new)
old = "        evidence['step'] = 'simulator boot'\n"
new = old + "        setup_probe_thread = threading.Thread(target=setup_probe, daemon=True)\n        setup_probe_thread.start()\n"
assert text.count(old) == 1
text = text.replace(old,new)
old = "            location.result()\n        server = ThreadingHTTPServer"
new = "            location.result()\n        setup_probe_stop.set()\n        if setup_probe_thread:\n            setup_probe_thread.join(timeout=9)\n        server = ThreadingHTTPServer"
assert text.count(old) == 1
text = text.replace(old,new)
old = "    finally:\n        probe_stop.set()"
new = "    finally:\n        setup_probe_stop.set()\n        if setup_probe_thread:\n            setup_probe_thread.join(timeout=9)\n        evidence['setup_host_probe'] = setup_probe_records\n        probe_stop.set()"
assert text.count(old) == 1
text = text.replace(old,new)
path.write_text(text)
