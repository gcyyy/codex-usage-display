"""Export only the explicit local Codex++ bridge changes; no user configuration."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.reference' / 'CodexPlusPlus-1.10.0'
BASE = '85f9117fe108719c6e4807ec60025a25042345f9'
FILES = [
    'crates/codex-plus-core/src/usage_status.rs',
    'crates/codex-plus-core/src/lib.rs',
    'crates/codex-plus-core/src/routes.rs',
    'crates/codex-plus-core/tests/bridge_routes.rs',
    'assets/inject/renderer-inject/91-extension-api.js',
    'assets/inject/renderer-inject/manifest.json',
    'assets/inject/renderer-inject.js',
    'apps/codex-plus-manager/src/renderer-inject.test.ts',
]


def main():
    subprocess.run(['git', 'add', '-N', FILES[0]], cwd=SOURCE, check=True)
    patch = subprocess.run(['git', 'diff', '--binary', BASE, '--', *FILES], cwd=SOURCE,
                           check=True, capture_output=True).stdout
    if not patch:
        raise RuntimeError('No bridge patch found')
    destination = ROOT / 'integration' / 'codex-plus-1.10.0-usage-bridge.patch'
    destination.parent.mkdir(exist_ok=True)
    destination.write_bytes(patch)
    (destination.parent / 'source.json').write_text(json.dumps({
        'upstream': 'https://github.com/BigPizzaV3/CodexPlusPlus',
        'upstreamCommit': BASE, 'upstreamVersion': '1.10.0', 'bridgeVersion': 1,
        'license': 'AGPL-3.0-only', 'patchSHA256': hashlib.sha256(patch).hexdigest(),
        'files': FILES,
        'sourceDirectory': '.reference/CodexPlusPlus-1.10.0',
        'patchFile': 'codex-plus-1.10.0-usage-bridge.patch',
        'compatibleHostSHA256': ['a5ad198c7e65a38bed5bd0480b7812c73080f6182ecf32d15c818d5f074f17e6'],
    }, indent=2), encoding='utf-8')
    print('Public bridge patch exported.')


if __name__ == '__main__':
    main()
