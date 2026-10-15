"""Explicit public-file allowlist. Never package pairing config, cache or real logs."""
import hashlib
import argparse
import json
import subprocess
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from collector import __version__

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "dist/codex-usage-collector.exe": "codex-usage-collector.exe",
    "userscript/usage-status.js": "userscript/codex-usage-status.js",
    "pricing/official-standard.json": "pricing/official-standard.json",
    "README.md": "README.md",
    "LICENSE": "LICENSE",
    "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
    "licenses/PYTHON.txt": "licenses/PYTHON.txt",
    "licenses/PYINSTALLER.txt": "licenses/PYINSTALLER.txt",
    "Install.cmd": "Install.cmd",
    "Uninstall.cmd": "Uninstall.cmd",
    "Start.cmd": "Start.cmd",
    "Stop.cmd": "Stop.cmd",
    "scripts/Uninstall.ps1": "scripts/Uninstall.ps1",
    "docs/INSTALLATION.md": "docs/INSTALLATION.md",
    "docs/RELEASING.md": "docs/RELEASING.md",
    "docs/COMPATIBILITY.md": "docs/COMPATIBILITY.md",
    "docs/TEST_RESULTS.md": "docs/TEST_RESULTS.md",
    "docs/BRIDGE_PROPOSAL.md": "docs/BRIDGE_PROPOSAL.md",
    "docs/LOG_ADAPTER.md": "docs/LOG_ADAPTER.md",
    "docs/log-version-evidence.json": "docs/log-version-evidence.json",
    "docs/IMAGE_PRICING.md": "docs/IMAGE_PRICING.md",
    "docs/image-pricing-evidence.json": "docs/image-pricing-evidence.json",
    "integration/README.md": "integration/README.md",
    "integration/codex-plus-1.8.0-usage-bridge.patch": "integration/codex-plus-1.8.0-usage-bridge.patch",
    "integration/source.json": "integration/source.json",
    "docs/exe-smoke.json": "docs/exe-smoke.json",
    "docs/benchmark.json": "docs/benchmark.json",
    "docs/benchmark-final.json": "docs/benchmark-final.json",
    "scripts/Start-Collector.ps1": "scripts/Start-Collector.ps1",
    "scripts/Stop-Collector.ps1": "scripts/Stop-Collector.ps1",
    "scripts/Pair-Script.ps1": "scripts/Pair-Script.ps1",
}


def import_bridge_package(package, root=ROOT):
    """Reuse a successful CI bridge only when its exact reviewed source still matches."""
    root = Path(root)
    info = json.loads((root/'integration/source.json').read_text(encoding='utf-8'))
    prefix = 'codex-usage-status/'
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read(prefix+'SHA256SUMS.json'))
        if len(archive.namelist()) != len(manifest)+1:
            raise ValueError('Unexpected cached package contents')
        for name, expected in manifest.items():
            path = PurePosixPath(name)
            if path.is_absolute() or '\\' in name or ':' in name or any(p in ('.','..') for p in name.split('/')):
                raise ValueError('Unsafe cached package path')
            with archive.open(prefix+name) as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest() != expected:
                    raise ValueError('Cached package checksum mismatch')
        build = json.loads(archive.read(prefix+'bridge/build.json'))
        if (build.get('testsExecuted') is not True or build.get('bridgeVersion') != info['bridgeVersion']
                or build.get('sourceCommit') != info['upstreamCommit'] or build.get('patchSHA256') != info['patchSHA256']
                or manifest.get('integration/codex-plus-1.8.0-usage-bridge.patch') != info['patchSHA256']
                or manifest.get('bridge/codex-plus-plus.exe') != build.get('sha256')):
            raise ValueError('Cached bridge differs from reviewed source or has no passing tests')
        native = archive.read(prefix+'bridge/codex-plus-plus.exe')
    target = root/'.reference/CodexPlusPlus/target/release/codex-plus-plus.exe'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(native)
    (root/'dist').mkdir(exist_ok=True)
    (root/'dist/bridge-host-build.json').write_text(json.dumps(build,indent=2),encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--with-bridge', action='store_true')
    parser.add_argument('--import-bridge-package', type=Path, help='Stage a verified same-source CI bridge; does not package a release')
    args = parser.parse_args()
    if args.import_bridge_package:
        import_bridge_package(args.import_bridge_package)
        print('Matching tested CI bridge staged; collector will be rebuilt separately.')
        return
    files = dict(FILES)
    for path in sorted((ROOT/'licenses').glob('TZDATA-*.txt')):
        name = str(path.relative_to(ROOT)).replace('\\','/')
        files[name] = name
    if args.with_bridge:
        source = ROOT / '.reference/CodexPlusPlus'
        build = json.loads((ROOT / 'dist/bridge-host-build.json').read_text(encoding='utf-8-sig'))
        info = json.loads((ROOT / 'integration/source.json').read_text(encoding='utf-8'))
        patch = ROOT / 'integration/codex-plus-1.8.0-usage-bridge.patch'
        actual = subprocess.check_output(['git','diff','--binary',info['upstreamCommit']], cwd=source)
        if hashlib.sha256(actual).hexdigest() != info['patchSHA256'] or hashlib.sha256(patch.read_bytes()).hexdigest() != info['patchSHA256']:
            raise RuntimeError('Bridge working source differs from reviewed patch')
        host = source / 'target/release/codex-plus-plus.exe'
        if not build['testsExecuted'] or hashlib.sha256(host.read_bytes()).hexdigest() != build['sha256'] or build['patchSHA256'] != info['patchSHA256']:
            raise RuntimeError('A tested, matching bridge build is required')
        bridge_dir = ROOT / 'dist/bridge'
        bridge_dir.mkdir(exist_ok=True)
        public_build = {k:build[k] for k in ('sha256','sourceCommit','bridgeVersion','patchSHA256','testsExecuted')}
        public_build['compatibleHostSHA256'] = ['48f062f9de96904c4c8169a8ccb0ee978fcca0d33cb1c75df9dee67c453a5d3d',
            'e5581705e865d135bac7e0c658ec8d8d4630ca26af030d6b717674e602d84863']
        (bridge_dir / 'build.json').write_text(json.dumps(public_build, indent=2), encoding='utf-8')
        names = subprocess.check_output(['git','ls-files','-z'], cwd=source).decode('utf-8').split('\0')
        # Tracked upstream source plus every reviewed patch file; never archive the workspace.
        with zipfile.ZipFile(bridge_dir / 'corresponding-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(set(filter(None, names)) | set(info['files'])):
                path = (source / name).resolve()
                if not path.is_relative_to(source.resolve()) or not path.is_file():
                    raise RuntimeError('Unexpected bridge source path')
                archive.write(path, 'CodexPlusPlus/' + name)
            archive.writestr('BUILDING.txt', 'AGPL-3.0-only. Upstream: ' + info['upstream'] + '\nBase commit: ' + info['upstreamCommit'] + '\nApply the distributed bridge patch to the base, or build the included already-patched source.\nFrontend: npm ci && npm run vite:build in apps/codex-plus-manager.\nRust 1.99.0 / MSVC: cargo build --locked --release -p codex-plus-manager --bin codex-plus-plus\nSee the accompanying repository scripts/Build-BridgeHost.ps1 and docs/RELEASING.md for tests and dependencies.\n')
        files.update({str(host.relative_to(ROOT)).replace('\\','/'):'bridge/codex-plus-plus.exe',
            'dist/bridge/build.json':'bridge/build.json', 'dist/bridge/corresponding-source.zip':'bridge/corresponding-source.zip'})
    release = ROOT / 'dist/release.json'
    release.parent.mkdir(exist_ok=True)
    release.write_text(json.dumps({'schemaVersion':1,'version':__version__,'platform':'windows-x64',
        'bundleBridge':args.with_bridge,'license':'AGPL-3.0-only'}, indent=2), encoding='utf-8')
    files['dist/release.json'] = 'release.json'
    manifest = {dst: hashlib.sha256((ROOT/src).read_bytes()).hexdigest() for src,dst in files.items()}
    (ROOT/"dist"/"SHA256SUMS.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    suffix = 'windows-x64' if args.with_bridge else 'collector-only-windows-x64'
    output=ROOT/"dist"/f"codex-usage-display-{__version__}-{suffix}.zip"
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for src,dst in files.items():
            info=zipfile.ZipInfo("codex-usage-status/"+dst,date_time=(2026,10,15,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,(ROOT/src).read_bytes())
        archive.writestr("codex-usage-status/SHA256SUMS.json",json.dumps(manifest,indent=2))
    print("Windows release packaged from public-file allowlist.")
    (ROOT/'dist'/'SHA256SUMS.txt').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n', encoding='utf-8')


if __name__=="__main__":main()
