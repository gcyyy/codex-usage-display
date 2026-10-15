"""Per-user Windows installation. Never write into official Codex homes or binaries."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path, PurePosixPath

from . import __version__

RECEIPT = 'installation.json'
SCRIPT_KEY = 'user:codex-usage-status.js'
BRIDGE_FILES = {'bridge/codex-plus-plus.exe', 'bridge/build.json', 'bridge/corresponding-source.zip'}


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.install-' + uuid.uuid4().hex)
    temp.write_bytes(data)
    for attempt in range(40):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 39:
                temp.unlink(missing_ok=True)
                raise
            time.sleep(.25)


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def remove_file(path):
    # A stopped Windows one-file EXE can retain its image handle briefly.
    for attempt in range(40):
        try:
            Path(path).unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(.25)


def verify_package(root):
    root = Path(root).resolve()
    manifest = read_json(root / 'SHA256SUMS.json')
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError('Empty release manifest')
    for name, expected in manifest.items():
        parts = PurePosixPath(name)
        if (not name or '\\' in name or ':' in name or parts.is_absolute()
                or any(p in ('.', '..') for p in name.split('/'))):
            raise ValueError('Unsafe release path')
        if parts.parts[0] not in {'bridge','scripts','userscript','pricing','docs','integration','licenses',
                'Install.cmd','Uninstall.cmd','Start.cmd','Stop.cmd','README.md','LICENSE',
                'THIRD_PARTY_NOTICES.md','codex-usage-collector.exe','release.json'}:
            raise ValueError('Release contains a private or unexpected path')
        target = (root / name).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError('Release file missing or outside package')
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected) or checksum(target) != expected:
            raise ValueError('Release checksum mismatch')
    for name in ('codex-usage-collector.exe', 'userscript/codex-usage-status.js', 'pricing/official-standard.json', 'release.json', 'LICENSE'):
        if name not in manifest:
            raise ValueError('Incomplete release')
    metadata = read_json(root / 'release.json')
    if metadata.get('version') != __version__ or metadata.get('schemaVersion') != 1:
        raise ValueError('Release/installer version mismatch')
    if metadata.get('bundleBridge') and not BRIDGE_FILES <= manifest.keys():
        raise ValueError('Bridge binary and corresponding source must ship together')
    return manifest, metadata


class Transaction:
    def __init__(self, backup):
        self.backup = Path(backup)
        self.entries = []

    def save(self, path):
        path = Path(path)
        if any(e['path'] == str(path) for e in self.entries):
            return
        backup = self.backup / str(len(self.entries))
        if path.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        entry = {'path': str(path), 'backup': str(backup) if path.exists() else None}
        self.entries.append(entry)
        self.backup.mkdir(parents=True, exist_ok=True)
        atomic(self.backup / 'journal.json', json_bytes(self.entries))

    def write(self, path, data):
        if Path(path).exists() and Path(path).read_bytes() == data:
            return
        self.save(path)
        atomic(path, data)

    def rollback(self):
        failures = []
        for entry in reversed(self.entries):
            path = Path(entry['path'])
            try:
                if entry['backup']:
                    backup = Path(entry['backup'])
                    if path.exists() and checksum(path) == checksum(backup):
                        continue
                    atomic(path, backup.read_bytes())
                else:
                    remove_file(path)
            except OSError as error:
                failures.append(error)
        if failures:
            raise failures[0]


def run(exe, *args):
    result = subprocess.run([str(exe), *map(str, args)], capture_output=True, timeout=35,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Collector command failed: ' + str(args[-1]))
    return result.stdout


def background(argv, **options):
    # Independent services must not reuse an installer's temporary one-file bundle.
    environment = {**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT':'1'}
    reset = None
    if os.name == 'nt' and getattr(sys, 'frozen', False):
        import ctypes
        reset = ctypes.windll.kernel32.SetDllDirectoryW
        reset.argtypes = [ctypes.c_wchar_p]
        reset.restype = ctypes.c_int
        reset(None)
    try:
        return subprocess.Popen(argv, env=environment, **options)
    finally:
        if reset:
            reset(getattr(sys, '_MEIPASS', None))


def start(exe, state):
    try:
        run(exe, '--state', state, 'diagnose')
        return
    except RuntimeError:
        pass
    process = background([str(exe), '--state', str(state), 'serve'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Collector exited; inspect configuration and port')
        try:
            run(exe, '--state', state, 'diagnose')
            return
        except RuntimeError:
            time.sleep(.25)
    raise RuntimeError('Collector startup timed out')


def manager_processes(exe, include_workers=False):
    # Fixed PowerShell program, path comparison happens in Python; no string-built commands.
    script = "Get-CimInstance Win32_Process -Filter \"Name='codex-plus-plus.exe'\" | Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], capture_output=True,
        text=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Cannot inspect bridge manager process identity')
    rows = json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(rows, dict):
        rows = [rows]
    return [r['ProcessId'] for r in rows if r.get('ExecutablePath')
        and Path(r['ExecutablePath']).resolve() == Path(exe).resolve()
        and (include_workers or '--codex-plus-multi-worker' not in (r.get('CommandLine') or ''))]


def stop_manager(exe):
    for pid in manager_processes(exe):
        result = subprocess.run(['taskkill.exe', '/F', '/PID', str(pid)], capture_output=True, timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError('Bridge manager could not stop')


def start_manager(exe):
    startup = subprocess.STARTUPINFO() if os.name == 'nt' else None
    if startup:
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    background([str(exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), startupinfo=startup)


def paths(args):
    install = (args.install_dir or Path(os.environ['LOCALAPPDATA']) / 'Programs/CodexUsageStatus').resolve()
    plus = (args.codex_plus_dir or Path(os.environ['APPDATA']) / 'Codex++').resolve()
    host = (args.host_exe or Path(os.environ['LOCALAPPDATA']) / 'Programs/Codex++/codex-plus-plus.exe').resolve()
    host_state = (args.host_state or Path(os.environ.get('CODEX_PLUS_STATE_DIR') or Path.home() / '.codex-session-delete')).resolve()
    return install, plus, host, host_state


def install(args):
    root = args.package_root.resolve()
    manifest, metadata = verify_package(root)
    target, plus, host, host_state = paths(args)
    if root == target or target.is_relative_to(root):
        raise ValueError('Extract the package outside the installation directory')
    if target == Path(target.anchor) or target == Path.home().resolve() or target in (plus, host_state):
        raise ValueError('Choose a dedicated installation directory')
    if target.exists() and not (target/'codex-usage-collector.exe').exists() and any(
            p.is_file() and p.relative_to(target).parts[0] not in {'.runtime','.installation-backups'}
            for p in target.rglob('*')):
        raise ValueError('Installation directory contains unrelated files')
    settings_path = plus / 'user_scripts.json'
    settings = read_json(settings_path)
    if not isinstance(settings, dict) or not isinstance(settings.get('scripts', {}), dict):
        raise ValueError('Install and launch Codex++ first')
    old = read_json(target / RECEIPT) if (target / RECEIPT).exists() else {}
    old_manifest = read_json(target / 'SHA256SUMS.json') if (target / 'SHA256SUMS.json').exists() else {}
    exe, state = target / 'codex-usage-collector.exe', target / '.runtime'
    if exe.exists() and checksum(exe) != old_manifest.get(exe.name):
        raise ValueError('Existing collector is not recognized; preserve it and stop')
    if args.install_bridge:
        if not metadata.get('bundleBridge') or not host.is_file():
            raise ValueError('The full bridge package and an existing Codex++ installation are required')
        build = read_json(root / 'bridge/build.json')
        if build['sha256'] != manifest['bridge/codex-plus-plus.exe']:
            raise ValueError('Bridge metadata checksum mismatch')
        allowed = set(build['compatibleHostSHA256']) | {build['sha256']}
        if old.get('hostSHA256'):
            allowed.add(old['hostSHA256'])
        if checksum(host) not in allowed:
            raise ValueError('Unsupported Codex++ binary; do not replace an unverified version')
        if checksum(host) != build['sha256'] and len(manager_processes(host, True)) > len(manager_processes(host)):
            raise ValueError('Close Codex++ multi-worker windows before replacing the shared manager EXE')
    elif not (host_state / 'usage-status.json').is_file():
        raise ValueError('Use Install.cmd for the bundled bridge, or pair a supported host first')
    transaction = Transaction(target / '.installation-backups' / uuid.uuid4().hex)
    stopped, host_changed = False, False
    script_path = plus / 'user_scripts/codex-usage-status.js'
    pairing_path = host_state / 'usage-status.json'
    external_before = old.get('externalOriginal', [])
    try:
        if exe.exists():
            run(exe, '--state', state, 'stop')
            stopped = True
        for name in manifest:
            transaction.write(target / name, (root / name).read_bytes())
        transaction.write(target / 'SHA256SUMS.json', (root / 'SHA256SUMS.json').read_bytes())
        transaction.save(state / 'config.json')
        run(exe, '--state', state, 'init')
        config = read_json(state / 'config.json')
        if not re.fullmatch('[A-Za-z0-9_-]{32,128}', config['pairingToken']):
            raise ValueError('Invalid local pairing token')
        for path in (script_path, settings_path, pairing_path):
            transaction.save(path)
        # Preserve the first installation baseline across upgrades.
        if not external_before:
            external_before = [dict(e) for e in transaction.entries if e['path'] in map(str, (script_path, settings_path, pairing_path))]
        source = (root / 'userscript/codex-usage-status.js').read_text(encoding='utf-8')
        if source.count('/*__PAIRING_CONFIG__*/null') != 1:
            raise ValueError('Invalid unpaired script template')
        paired = source.replace('/*__PAIRING_CONFIG__*/null', '{"transport":"bridge"}').encode('utf-8')
        transaction.write(script_path, paired)
        settings['enabled'] = True
        settings.setdefault('scripts', {})[SCRIPT_KEY] = True
        transaction.write(settings_path, json_bytes(settings))
        transaction.write(pairing_path, json_bytes({'schemaVersion':1, 'enabled':True,
            'port':config['port'], 'pairingToken':config['pairingToken']}))
        original_host = old.get('originalHost')
        if args.install_bridge and checksum(host) != build['sha256']:
            transaction.save(host)
            if not original_host:
                original_host = dict(next(e for e in transaction.entries if e['path'] == str(host)))
            stop_manager(host)
            host_changed = True
            transaction.write(host, (root / 'bridge/codex-plus-plus.exe').read_bytes())
            start_manager(host)
        start(exe, state)
        record = {'schemaVersion':1, 'version':__version__, 'installDirectory':str(target),
            'files':manifest, 'externalOriginal':external_before, 'originalHost':original_host,
            'hostPath':str(host), 'hostSHA256':checksum(host) if args.install_bridge else old.get('hostSHA256'),
            'scriptPath':str(script_path), 'scriptSHA256':hashlib.sha256(paired).hexdigest(),
            'settingsPath':str(settings_path), 'pairingPath':str(pairing_path),
            'migratedLegacy':old.get('migratedLegacy', bool(old_manifest and not old)),
            'pairingSHA256':checksum(pairing_path), 'backupDirectory':str(transaction.backup)}
        transaction.write(target / RECEIPT, json_bytes(record))
    except Exception as original_error:
        recovery_errors = []
        # Stop only our newly copied collector before restoring a running executable.
        if exe.exists():
            try:
                run(exe, '--state', state, 'stop')
            except (OSError, RuntimeError):
                pass
        if host_changed:
            try:
                stop_manager(host)
            except (OSError, RuntimeError) as error:
                recovery_errors.append(error)
        try:
            transaction.rollback()
        except OSError as error:
            recovery_errors.append(error)
        if host_changed:
            try:
                start_manager(host)
            except OSError as error:
                recovery_errors.append(error)
        if stopped:
            try:
                start(exe, state)
            except (OSError, RuntimeError) as error:
                recovery_errors.append(error)
        if recovery_errors:
            raise RuntimeError('Installation failed; recovery incomplete. Backups retained in the install directory.') from original_error
        raise
    print(json.dumps({'status':'installed', 'version':__version__, 'transport':'bridge',
        'configurationPreserved':True, 'nextStep':'Hot reload user scripts in Codex++'}))


def uninstall(args):
    target, _, _, _ = paths(args)
    record = read_json(target / RECEIPT)
    if record.get('schemaVersion') != 1 or Path(record['installDirectory']).resolve() != target:
        raise ValueError('No recognized installation receipt')
    exe = target / 'codex-usage-collector.exe'
    if exe.exists():
        if checksum(exe) != record['files'][exe.name]:
            raise ValueError('Installed collector was modified; preserve it')
        run(exe, '--state', target / '.runtime', 'stop')
    original = {e['path']:e for e in record['externalOriginal']}
    settings_path = Path(record['settingsPath'])
    settings = read_json(settings_path)
    previous_settings = original.get(str(settings_path), {})
    previous = read_json(previous_settings['backup']) if previous_settings.get('backup') else {}
    prior_scripts = previous.get('scripts', {})
    if record.get('migratedLegacy'):
        prior_scripts.pop(SCRIPT_KEY, None)
    if SCRIPT_KEY in prior_scripts:
        settings.setdefault('scripts', {})[SCRIPT_KEY] = prior_scripts[SCRIPT_KEY]
    else:
        settings.get('scripts', {}).pop(SCRIPT_KEY, None)
    other = lambda s: {k:v for k,v in s.get('scripts', {}).items() if k != SCRIPT_KEY}
    if other(settings) == other(previous) and 'enabled' in previous:
        settings['enabled'] = previous['enabled']
    atomic(settings_path, json_bytes(settings))
    retained = []
    for field, hash_field in (('scriptPath','scriptSHA256'), ('pairingPath','pairingSHA256')):
        path = Path(record[field])
        if path.exists() and checksum(path) != record[hash_field]:
            retained.append(path.name)
            continue
        entry = original.get(str(path))
        if entry and entry['backup'] and not record.get('migratedLegacy'):
            atomic(path, Path(entry['backup']).read_bytes())
        else:
            remove_file(path)
    if record.get('originalHost'):
        host = Path(record['hostPath'])
        if host.exists() and checksum(host) == record['hostSHA256']:
            stop_manager(host)
            atomic(host, Path(record['originalHost']['backup']).read_bytes())
            start_manager(host)
        else:
            retained.append('modified bridge host')
    # Delete individual, unchanged owned files only. Keep data and recovery backups.
    for name, digest in record['files'].items():
        path = (target / name).resolve()
        if not path.is_relative_to(target):
            raise ValueError('Unsafe receipt path')
        if path.exists() and checksum(path) == digest:
            remove_file(path)
        elif path.exists():
            retained.append(name)
    (target / 'SHA256SUMS.json').unlink(missing_ok=True)
    (target / RECEIPT).unlink(missing_ok=True)
    print(json.dumps({'status':'uninstalled','dataAndBackupsRetained':True,'modifiedFilesRetained':retained}))
