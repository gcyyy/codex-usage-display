import copy
import hashlib
import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
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

    def test_candidates_include_skipped_older_tags_and_exclude_known(self):
        newest = dict(self.baseline, version='0.167.0-alpha.4', tag='rust-v0.167.0-alpha.4')
        tags = ['rust-v0.166.0-alpha.6', 'rust-v0.167.0-alpha.4',
                'rust-v0.167.0-alpha.5', 'rust-v0.166.0-alpha.5', 'bad;tag']
        self.assertEqual(check.candidate_tags(tags, [self.baseline, newest]),
                         ['rust-v0.166.0-alpha.6', 'rust-v0.167.0-alpha.5'])
        many = [f'rust-v0.167.0-alpha.{n}' for n in range(1, 41)]
        selected = check.candidate_tags(many, [self.baseline], limit=3)
        self.assertEqual(selected, ['rust-v0.167.0-alpha.38', 'rust-v0.167.0-alpha.39', 'rust-v0.167.0-alpha.40'])

    def test_pending_adapter_pr_filter_excludes_unrelated_and_forks(self):
        def pr(n, repo='owner/repo', author='github-actions[bot]', ref='codex/log-adapter-batch-abc', state='open'):
            return {'number': n, 'state': state, 'user': {'login': author},
                    'head': {'ref': ref, 'repo': {'full_name': repo}}}
        pulls = [pr(1), pr(2, repo='fork/repo'), pr(3, author='human'),
                 pr(4, ref='feature/test'), pr(5, state='closed')]
        self.assertEqual(check.pending_adapter_prs(pulls, 'owner/repo'), [1])

    def test_prepare_batch_increments_once_and_preserves_latest_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'collector').mkdir(); (root / 'docs').mkdir()
            (root / 'collector/indexer.py').write_text('PARSER_VERSION = "9"\nSUPPORTED_VERSIONS = {"0.166.0-alpha.5.1", "synthetic-v1"}\n')
            (root / 'docs/log-version-evidence.json').write_text(json.dumps([self.baseline]))
            matches = [('rust-v0.166.0-alpha.6', 'b'*40, self.hashes),
                       ('rust-v0.167.0-alpha.1', 'c'*40, self.hashes)]
            check.prepare_many(root, self.baseline, matches)
            data = json.loads((root / 'docs/log-version-evidence.json').read_text())
            self.assertEqual([e['version'] for e in data], ['0.166.0-alpha.5.1', '0.166.0-alpha.6', '0.167.0-alpha.1'])
            source = (root / 'collector/indexer.py').read_text()
            self.assertIn('PARSER_VERSION = "10"', source)
            self.assertIn('"0.166.0-alpha.6"', source)
            self.assertIn('"0.167.0-alpha.1"', source)

    def test_batch_skips_changed_tag_and_prepares_other_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'collector').mkdir(); (root / 'docs').mkdir()
            (root / 'collector/indexer.py').write_text('PARSER_VERSION = "8"\nSUPPORTED_VERSIONS = {"0.166.0-alpha.5.1", "synthetic-v1"}\n')
            (root / 'docs/log-version-evidence.json').write_text(json.dumps([self.baseline]))
            argv = ['check', '--source', '.', '--tag', 'rust-v0.166.0-alpha.6', '--tag', 'rust-v0.167.0-alpha.1', '--apply']
            results = [('b'*40, self.hashes), check.UpstreamChanged('Upstream source changed: item')]
            output = io.StringIO()
            with patch.object(check, 'ROOT', root), patch.object(check, 'compare', side_effect=results), patch('sys.argv', argv), redirect_stdout(output):
                self.assertEqual(check.main(), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['matched'], ['rust-v0.166.0-alpha.6'])
            self.assertEqual(result['changed'][0]['tag'], 'rust-v0.167.0-alpha.1')
            self.assertNotIn('0.167.0-alpha.1', (root / 'collector/indexer.py').read_text())


if __name__ == '__main__':
    unittest.main()
