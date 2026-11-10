"""Compare reviewed upstream Rust blocks and prepare a reviewable adapter update.

This is a maintainer tool, not a runtime trust decision. No upstream code is run.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG = re.compile(r'rust-v(\d+)\.(\d+)\.(\d+)(?:-alpha\.(\d+(?:\.\d+)*))?\Z')
BLOCKS = {
    'pub(crate) fn record_token_usage(': 'codex-rs/core/src/state/session.rs',
    'pub struct TokenUsageRecord {': 'codex-rs/protocol/src/protocol.rs',
    'pub struct TokenUsage {': 'codex-rs/protocol/src/protocol.rs',
    'pub(crate) async fn record_response_token_usage(': 'codex-rs/core/src/session/mod.rs',
    'pub(crate) async fn record_observed_response_completed(': 'codex-rs/core/src/session/mod.rs',
    'pub(crate) async fn record_incomplete_response_usage(': 'codex-rs/core/src/session/mod.rs',
}


def version_key(tag):
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError('Unsupported upstream tag format')
    major, minor, patch, alpha = match.groups()
    return int(major), int(minor), int(patch), 1 if alpha is None else 0, tuple(map(int, alpha.split('.'))) if alpha else ()


def latest_tag(tags, baseline):
    candidates = [t for t in tags if TAG.fullmatch(t) and version_key(t) > version_key(baseline)]
    return max(candidates, key=version_key) if candidates else None


SCAN_FLOOR = 'rust-v0.166.0-alpha.5.1'


def pending_adapter_prs(pulls, repository):
    """Only our own automated review branches block scheduled duplicate PRs."""
    return [p['number'] for p in pulls
            if p.get('state') == 'open'
            and p.get('user', {}).get('login') == 'github-actions[bot]'
            and (p.get('head', {}).get('repo') or {}).get('full_name') == repository
            and p.get('head', {}).get('ref', '').startswith('codex/log-adapter-')]


def candidate_tags(tags, evidence, limit=32):
    known = {e['tag'] for e in evidence}
    candidates = {t for t in tags if TAG.fullmatch(t) and version_key(t) >= version_key(SCAN_FLOOR) and t not in known}
    # Keep checking new versions even if older versions need a manual review.
    return sorted(candidates, key=version_key)[-limit:]


class UpstreamChanged(ValueError):
    pass


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode('utf-8')


def block(source, marker):
    # Rust items at known indentation: require a unique declaration and a closing brace
    # at precisely the declaration indentation. Ambiguous or changed layouts fail closed.
    lines = source.splitlines(keepends=True)
    found = [i for i, line in enumerate(lines) if line.lstrip().startswith(marker)]
    if len(found) != 1:
        raise ValueError('Missing or ambiguous declaration: ' + marker)
    start = found[0]
    indent = lines[start][:len(lines[start]) - len(lines[start].lstrip())]
    for end in range(start + 1, len(lines)):
        if lines[end].rstrip('\r\n') == indent + '}':
            return ''.join(lines[start:end + 1]).lstrip().rstrip('\r\n')
    raise ValueError('Missing item end: ' + marker)


def compare(repo, baseline, tag):
    version_key(tag)
    base_commit = git(repo, 'rev-parse', baseline['tag'] + '^{commit}').strip()
    if base_commit != baseline['commit']:
        raise ValueError('Baseline tag does not resolve to reviewed commit')
    target_commit = git(repo, 'rev-parse', tag + '^{commit}').strip()
    if not re.fullmatch('[0-9a-f]{40}', target_commit):
        raise ValueError('Invalid upstream commit')
    if tag == baseline['tag']:
        raise ValueError('Target is already the reviewed baseline')
    hashes = {}
    for marker, path in BLOCKS.items():
        before = block(git(repo, 'show', base_commit + ':' + path), marker)
        after = block(git(repo, 'show', target_commit + ':' + path), marker)
        value = hashlib.sha256(before.encode('utf-8')).hexdigest()
        expected = baseline.get('unchangedSourceBlocks', {}).get(marker)
        if expected != value:
            raise ValueError('Baseline evidence mismatch: ' + marker)
        if before != after:
            raise UpstreamChanged('Upstream source changed: ' + marker)
        hashes[marker] = value
    return target_commit, hashes


def prepare_many(root, baseline, matches):
    evidence_path = root / 'docs/log-version-evidence.json'
    index_path = root / 'collector/indexer.py'
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    if evidence[-1] != baseline or not matches:
        raise ValueError('Evidence changed or no matching tags')
    source = index_path.read_text(encoding='utf-8')
    marker = '"synthetic-v1"}'
    if source.count(marker) != 1:
        raise ValueError('Supported version list has unexpected layout')
    versions = []
    for tag, commit, hashes in matches:
        version_key(tag)
        version = tag.removeprefix('rust-v')
        if any(e['version'] == version for e in evidence) or version in versions:
            raise ValueError('Target already exists')
        versions.append(version)
        entry = {'version': version, 'tag': tag, 'commit': commit,
                 'recordFields': baseline['recordFields'], 'localThreadAccumulator': True,
                 'perResponseUsage': True, 'sourceFunctionSHA256': hashes['pub(crate) fn record_token_usage('],
                 'verifiedAgainst': baseline['version'], 'unchangedSourceBlocks': hashes,
                 'notes': 'Automatically compared critical blocks; review surrounding changes and run regression tests before merging.'}
        evidence.append(entry)
    evidence.sort(key=lambda e: version_key(e['tag']))
    source = source.replace(marker, ', '.join('"' + v + '"' for v in versions) + ', ' + marker)
    source, count = re.subn(r'PARSER_VERSION = "(\d+)"', lambda m: 'PARSER_VERSION = "' + str(int(m.group(1)) + 1) + '"', source)
    if count != 1:
        raise ValueError('Parser version has unexpected layout')
    index_path.write_text(source, encoding='utf-8')
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def prepare(root, baseline, tag, commit, hashes):
    prepare_many(root, baseline, [(tag, commit, hashes)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Fetched official upstream git repository')
    parser.add_argument('--tag', action='append', help='Exact upstream rust-v tag; repeat for a batch')
    parser.add_argument('--apply', action='store_true', help='Generate local changes after successful comparison')
    args = parser.parse_args()
    try:
        evidence = json.loads((ROOT / 'docs/log-version-evidence.json').read_text(encoding='utf-8'))
        baseline = evidence[-1]
        tags = args.tag or candidate_tags(git(args.source, 'tag', '--list', 'rust-v*').splitlines(), evidence)
        if not tags:
            print(json.dumps({'status': 'no_new_version'})); return 0
        known = {e['tag'] for e in evidence}
        if len(set(tags)) != len(tags) or any(tag in known for tag in tags):
            raise ValueError('Target is already verified or duplicated')
        matches, changed = [], []
        for tag in tags:
            try:
                commit, hashes = compare(args.source, baseline, tag)
                matches.append((tag, commit, hashes))
            except UpstreamChanged as exc:
                changed.append({'tag': tag, 'reason': str(exc)})
        if args.apply and matches:
            prepare_many(ROOT, baseline, matches)
        print(json.dumps({'status': 'matched' if matches else 'needs_review',
                          'matched': [m[0] for m in matches], 'changed': changed,
                          'baseline': baseline['commit'], 'applied': bool(args.apply and matches)}))
        return 0 if matches else 1
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print('Compatibility check failed: ' + str(exc), file=__import__('sys').stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
