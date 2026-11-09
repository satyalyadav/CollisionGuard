import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('pilot', Path(__file__).resolve().parents[1] / 'scripts/parallact_pilot.py')
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


class PilotTests(unittest.TestCase):
    def test_hyphenated_repository_and_selection(self):
        paths = [f'dataset/v1/generated/complementary/instance_owner__repo-{i}-{i:040x}-vnan.json' for i in range(8)]
        self.assertEqual(pilot.parse_path(paths[0])['repo'], 'owner/repo-0')
        self.assertEqual(pilot.parse_path(paths[0].replace('-vnan.json', '.json'))['repo'], 'owner/repo-0')
        first, shortage = pilot.select(paths, set())
        self.assertEqual(first, pilot.select(list(reversed(paths)), set())[0])
        self.assertEqual(len(first), 2)
        self.assertFalse(shortage)

    def test_resume_rejects_drift(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            dest = p / 'response'
            dest.write_bytes(b'drift')
            meter = pilot.Meter(p / 'ledger')
            with self.assertRaises(ValueError):
                meter.fetch('https://example.invalid', 'repo', dest, pilot.digest(b'original'))

    def test_meter_counts_rejected_body_and_cache_reuse(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, n): return b'x' * n
        with tempfile.TemporaryDirectory() as d, patch.object(pilot, 'BODY', 5), patch.object(pilot.urllib.request, 'urlopen', return_value=Response()):
            p = Path(d)
            meter = pilot.Meter(p / 'ledger')
            with self.assertRaises(ValueError):
                meter.fetch('https://example.invalid', 'repo', p / 'body')
            self.assertEqual(json.loads((p / 'ledger').read_text())['charged_bytes'], 5)
            (p / 'cached').write_bytes(b'abc')
            meter.fetch('https://example.invalid', 'repo', p / 'cached', pilot.digest(b'abc'))
            self.assertEqual(meter.state['cache_reuse_bytes'], 3)


if __name__ == '__main__':
    unittest.main()
