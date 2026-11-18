from pathlib import Path

path = Path('launch_check.py')
text = path.read_text()
def replace(old, new):
    global text
    assert text.count(old) == 1, old
    text = text.replace(old, new)

anchor = "        # Stall injection/replay is an explicit diagnostic, not part of each release launch."
helper = '''        def replay_capture(stage, process=None):
            # Content-free freeze fields only; read existing files, never change them.
            sample = {'stage': stage, 'at': time.time(), 'process': process}
            file = container / 'Library/Application Support/main-thread-freeze.json'
            try:
                record = json.loads(file.read_text())
                sample['file'] = {k: record.get(k) for k in ('observed_at', 'stuck_seconds', 'action', 'version')}
            except FileNotFoundError:
                sample['file'] = None
            except (OSError, ValueError) as exc:
                sample['file_error'] = type(exc).__name__
            try:
                prefs = plistlib.loads((container / 'Library/Preferences/com.fairystack.ios.plist').read_bytes())
                rows = json.loads(prefs.get('deviceDiagnostics.queue.v1', b'[]'))
                sample['previous'] = [{k: event.get(k) for k in ('id', 'run_id', 'observed_at', 'steps')}
                    for row in rows if (event := row.get('event', {})).get('operation') == 'previous_freeze']
            except (OSError, ValueError, TypeError) as exc:
                sample['queue_error'] = type(exc).__name__
            evidence.setdefault('replay_evidence', []).append(sample)

'''
replace(anchor, helper + anchor)
anchor = "            # Block the real main thread for 6 seconds and inspect its independently saved record."
replace(anchor, "            replay_capture('before_injection')\n" + anchor)
old = "            run('xcrun', 'simctl', 'launch', '--terminate-running-process', sim, 'com.fairystack.ios',\n                env=env, timeout=60)\n            time.sleep(9)"
new = "            injected_process = run('xcrun', 'simctl', 'launch', '--terminate-running-process', sim, 'com.fairystack.ios',\n                env=env, timeout=60)\n            replay_capture('injection_process_started', injected_process)\n            time.sleep(9)\n            replay_capture('after_injection', injected_process)"
replace(old,new)
old = "                run('xcrun', 'simctl', 'launch', '--terminate-running-process', sim, 'com.fairystack.ios',\n                    env=env, timeout=60)\n                # Cold process startup"
new = "                replay_capture('before_replay_'+str(launch+1))\n                replay_process = run('xcrun', 'simctl', 'launch', '--terminate-running-process', sim, 'com.fairystack.ios',\n                    env=env, timeout=60)\n                replay_capture('replay_started_'+str(launch+1), replay_process)\n                previous_capture = None\n                # Cold process startup"
replace(old,new)
old = "                    ready = sum(row.get('watchdog_ready') is True for row in json.loads(events.read_text())) > ready_before"
new = old + "\n                    signature = (exists, tuple(row['event'].get('id') for row in previous))\n                    if signature != previous_capture:\n                        replay_capture('replay_change_'+str(launch+1), replay_process)\n                        previous_capture = signature"
replace(old,new)
old = "                ids = [row['event']['id'] for row in previous]"
replace(old, "                replay_capture('after_replay_'+str(launch+1), replay_process)\n" + old)
path.write_text(text)
