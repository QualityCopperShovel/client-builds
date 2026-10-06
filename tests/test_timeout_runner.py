import subprocess
import sys
import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[1] / 'scripts' / 'run_with_timeout.py'


class TimeoutRunnerTests(unittest.TestCase):
    def test_returns_child_status(self):
        completed = subprocess.run(
            [sys.executable, str(RUNNER), '2', sys.executable, '-c',
             'raise SystemExit(7)'], timeout=5, check=False)
        self.assertEqual(completed.returncode, 7)

    def test_terminates_never_resolving_child(self):
        completed = subprocess.run(
            [sys.executable, str(RUNNER), '1', sys.executable, '-c',
             'import time; time.sleep(30)'], timeout=5, check=False,
            capture_output=True, text=True)
        self.assertEqual(completed.returncode, 124)
        self.assertIn('Timed out after 1s', completed.stderr)


if __name__ == '__main__':
    unittest.main()
