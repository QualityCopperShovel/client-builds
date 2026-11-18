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
path.write_text(text)
