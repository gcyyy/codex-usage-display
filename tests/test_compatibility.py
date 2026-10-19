import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from collector.compatibility import HostCompatibility, check_installation, log_compatibility


class CompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = self.root / 'host.exe'
        self.host.write_bytes(b'verified-host')
        (self.root / 'installation.json').write_text(json.dumps({'hostPath': str(self.host),
            'hostSHA256': hashlib.sha256(self.host.read_bytes()).hexdigest()}))

    def test_changed_host_detected_without_replacing_or_downgrading(self):
        monitor = HostCompatibility(self.root)
        with patch('collector.compatibility.time.monotonic', side_effect=[1, 2, 62, 123]):
            self.assertEqual(monitor.check()['status'], 'matches_installation')
            self.host.write_bytes(b'upstream-new-version')
            self.assertEqual(monitor.check()['status'], 'matches_installation')  # bounded cache
            report = monitor.enrich({'issues': []})
            self.assertEqual(report['status'], 'attention')
            self.assertEqual(report['issues'][0]['code'], 'host_changed')
            self.host.unlink()
            self.assertEqual(monitor.check()['status'], 'missing')
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_missing_receipt_then_restored_is_rechecked(self):
        monitor = HostCompatibility(self.root)
        p = self.root / 'installation.json'; original = p.read_bytes()
        with patch('collector.compatibility.time.monotonic', side_effect=[1, 62, 123]):
            self.assertEqual(monitor.check()['status'], 'matches_installation')
            p.unlink(); self.assertEqual(monitor.check()['status'], 'not_installed')
            p.write_bytes(original); self.assertEqual(monitor.check()['status'], 'matches_installation')

    def test_offline_check_still_finds_overwritten_host_without_initializing_config(self):
        self.host.write_bytes(b'upgraded')
        report = check_installation(self.root / 'absent-state', self.root)
        self.assertEqual(report['status'], 'attention')
        self.assertEqual({x['code'] for x in report['issues']}, {'host_changed', 'collector_offline'})
        self.assertEqual(report['logFormats']['status'], 'unchecked')
        self.assertFalse((self.root / 'absent-state').exists())

    def test_unknown_versions_count_once_and_exclude_unselected_sessions(self):
        sessions = {'a': {'meta': {'cli_version': '0.999.1'}}, 'b': {'meta': {'cli_version': 'synthetic-v1'}},
                    'c': {'meta': {'cli_version': '0.999.2'}}}
        records = [{'sessionId': x} for x in ['a', 'a', 'b', 'c']]
        report = log_compatibility(sessions, records, lambda sid: sid != 'c')
        self.assertEqual(report['logFormats']['status'], 'needs_adapter')
        self.assertEqual(report['logFormats']['versions'], [
            {'version': '0.999.1', 'records': 2, 'supported': False},
            {'version': 'synthetic-v1', 'records': 1, 'supported': True}])
        self.assertEqual(len(report['issues']), 1)
        self.assertEqual(log_compatibility(sessions, [], lambda sid: True)['logFormats']['status'], 'no_records')

    def test_malformed_receipt_is_inconclusive_not_healthy(self):
        (self.root / 'installation.json').write_text('{}')
        report = HostCompatibility(self.root).enrich({'issues': []})
        self.assertEqual(report['host']['status'], 'unchecked')
        self.assertEqual(report['status'], 'attention')

    def test_version_labels_do_not_expose_arbitrary_metadata(self):
        report = log_compatibility({'a': {'meta': {'cli_version': 'C:/private/token'}}},
                                   [{'sessionId': 'a'}], lambda sid: True)
        self.assertNotIn('private', json.dumps(report))
        self.assertEqual(report['logFormats']['versions'][0]['version'], 'unknown')
