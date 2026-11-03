import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import check_upstream_log as check


def fixture(marker):
    return marker + '\n    inner();\n}\n'


class UpstreamCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.contents = {marker: fixture(marker) for marker in check.BLOCKS}
        self.hashes = {marker: hashlib.sha256(text.rstrip('\n').encode()).hexdigest()
                       for marker, text in self.contents.items()}
        self.baseline = {'version': '0.166.0-alpha.5.1', 'tag': 'rust-v0.166.0-alpha.5.1',
                         'commit': 'a' * 40, 'recordFields': ['thread_id'],
                         'unchangedSourceBlocks': self.hashes}

    def fake_git(self, repo, *args):
        if args[0] == 'rev-parse':
            return ('a' if args[1].startswith(self.baseline['tag']) else 'b') * 40 + '\n'
        ref, path = args[1].split(':', 1)
        return '\n'.join(self.contents[k] for k, p in check.BLOCKS.items() if p == path)

    def test_matching_blocks_prepare_version_and_invalidate_cache(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(check, 'git', self.fake_git):
            root = Path(directory)
            (root / 'collector').mkdir(); (root / 'docs').mkdir()
            (root / 'collector/indexer.py').write_text('PARSER_VERSION = "8"\nSUPPORTED_VERSIONS = {"0.166.0-alpha.5.1", "synthetic-v1"}\n')
            (root / 'docs/log-version-evidence.json').write_text(json.dumps([self.baseline]))
            tag = 'rust-v0.167.0-alpha.1'
            commit, hashes = check.compare(root, self.baseline, tag)
            check.prepare(root, self.baseline, tag, commit, hashes)
            source = (root / 'collector/indexer.py').read_text()
            self.assertIn('PARSER_VERSION = "9"', source)
            self.assertIn('"0.167.0-alpha.1"', source)
            entry = json.loads((root / 'docs/log-version-evidence.json').read_text())[-1]
            self.assertEqual(entry['commit'], 'b' * 40)
            self.assertEqual(entry['unchangedSourceBlocks'], self.hashes)

    def test_changed_target_and_tampered_baseline_fail_closed(self):
        def changed(repo, *args):
            data = self.fake_git(repo, *args)
            return data.replace('inner();', 'changed();') if args[0] == 'show' and args[1].startswith('b' * 40) else data
        with patch.object(check, 'git', changed):
            with self.assertRaisesRegex(ValueError, 'Upstream source changed'):
                check.compare('.', self.baseline, 'rust-v0.167.0-alpha.1')
        baseline = copy.deepcopy(self.baseline)
        baseline['unchangedSourceBlocks'][next(iter(check.BLOCKS))] = '0' * 64
        with patch.object(check, 'git', self.fake_git):
            with self.assertRaisesRegex(ValueError, 'Baseline evidence mismatch'):
                check.compare('.', baseline, 'rust-v0.167.0-alpha.1')

    def test_missing_or_ambiguous_declaration_is_rejected(self):
        with self.assertRaises(ValueError): check.block('', 'pub struct Missing {')
        marker = 'pub struct Duplicate {'
        with self.assertRaises(ValueError): check.block(fixture(marker) * 2, marker)

    def test_selects_latest_version_without_matching_untrusted_tags(self):
        tags = ['rust-v0.167.0-alpha.2', 'rust-v0.167.0-alpha.10', 'rust-v0.167.0',
                'rust-v0.999.0;evil', 'anything', 'rust-v0.166.0-alpha.5.1']
        self.assertEqual(check.latest_tag(tags, self.baseline['tag']), 'rust-v0.167.0')
        with self.assertRaises(ValueError): check.version_key('rust-v0.167.0;evil')
        self.assertIsNone(check.latest_tag(['rust-v0.166.0-alpha.5.1'], self.baseline['tag']))


if __name__ == '__main__':
    unittest.main()
