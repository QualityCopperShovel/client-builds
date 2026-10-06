import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('codesign_retry', Path(__file__).resolve().parents[1] / 'scripts/codesign_with_retry.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class SigningRetryTests(unittest.TestCase):
    def test_transient_recovers_without_rebuilding_or_changing_command(self):
        run = Mock(side_effect=[subprocess.CompletedProcess([], 1, '', 'The timestamp service is not available.'), subprocess.CompletedProcess([], 0, '', '')])
        sleep = Mock()
        self.assertEqual(module.sign(['--timestamp', 'app.dmg'], run=run, sleep=sleep), 0)
        sleep.assert_called_once_with(3)
        self.assertEqual(run.call_args_list[0], run.call_args_list[1])
        self.assertEqual(run.call_args.args[0], ['codesign', '--timestamp', 'app.dmg'])

    def test_permanent_error_fails_immediately(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 1, '', 'no identity found'))
        sleep = Mock()
        self.assertEqual(module.sign(['app.dmg'], run=run, sleep=sleep), 1)
        run.assert_called_once(); sleep.assert_not_called()

    def test_outage_has_three_attempts_and_nine_seconds_backoff(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 1, '', 'The timestamp service is not available.'))
        sleep = Mock()
        self.assertEqual(module.sign(['app.dmg'], run=run, sleep=sleep), 1)
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [3, 6])

    def test_never_resolving_signer_and_overall_deadline_are_terminal(self):
        def stuck(command, **kwargs):
            return subprocess.run(['python3', '-c', 'import time;time.sleep(30)'], timeout=kwargs['timeout'])
        self.assertEqual(module.sign(['app.dmg'], run=stuck, attempt_seconds=.03), 124)
        run = Mock(return_value=subprocess.CompletedProcess([], 1, '', 'The timestamp service is not available.'))
        sleep = Mock()
        self.assertEqual(module.sign(['app.dmg'], run=run, clock=Mock(side_effect=[0, 0, 59]), sleep=sleep), 124)
        sleep.assert_not_called()

if __name__ == '__main__': unittest.main()
