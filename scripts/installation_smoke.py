"""Actual packaged EXE, isolated settings/home/port; never touches the user's apps."""
import json
import os
import socket
import subprocess
import time
import tempfile
import zipfile
from pathlib import Path
from collector import __version__
from collector.install import checksum

ROOT = Path(__file__).resolve().parent.parent


def main():
    archive = ROOT/'dist'/f'codex-usage-display-{__version__}-windows-x64.zip'
    output = ROOT/'tests/output'
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output, prefix='install-') as folder:
        root = Path(folder).resolve()
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if not (root/name).resolve().is_relative_to(root):
                    raise RuntimeError('Unsafe package archive path')
            z.extractall(root)
        package = root/'codex-usage-status'
        exe = package/'codex-usage-collector.exe'
        target = root/'installed 中文'
        plus = root/'Codex++'
        plus.mkdir()
        settings = plus/'user_scripts.json'
        settings.write_text(json.dumps({'enabled':False,'scripts':{'user:other.js':False},'unrelated':42}),encoding='utf-8')
        host = root/'host-state'
        host.mkdir()
        # Collector-only install path uses an already supported host's pairing.
        # No real manager process is started or replaced by this smoke test.
        config = {'schemaVersion':'1','port':0,'pairingToken':'synthetic-install-smoke-token-1234567890',
            'homes':[str(root/'empty-home')],'timezone':'Asia/Shanghai','allowedOrigins':['app://-']}
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));config['port'] = sock.getsockname()[1]
        (root/'empty-home/sessions').mkdir(parents=True)
        state = target/'.runtime';state.mkdir(parents=True)
        (state/'config.json').write_text(json.dumps(config),encoding='utf-8')
        (host/'usage-status.json').write_text('{}',encoding='utf-8')
        flags = getattr(subprocess,'CREATE_NO_WINDOW',0)

        def run(*args):
            result = subprocess.run([str(exe), *map(str,args)],capture_output=True,timeout=60,creationflags=flags)
            if result.returncode:
                # Only fixed installer diagnostics; no configuration or token output.
                raise RuntimeError(result.stderr.decode('utf-8',errors='replace'))
            return result.stdout

        options = ['--install-dir',target,'--codex-plus-dir',plus,'--host-state',host]
        run('verify-package','--package-root',package)
        try:
            for _ in range(2):
                run('install','--package-root',package,*options)
                assert json.loads((state/'config.json').read_text()) == config
                assert json.loads(settings.read_text())['unrelated'] == 42
                assert checksum(target/'codex-usage-collector.exe') == checksum(exe)
                assert config['pairingToken'] not in (plus/'user_scripts/codex-usage-status.js').read_text(encoding='utf-8')
            run('--state',state,'diagnose')
            # Exercise the shipped PowerShell wrapper: its temporary EXE must remove
            # the installed EXE while keeping the user's unrelated settings intact.
            removal = subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
                '-File',str(target/'scripts/Uninstall.ps1'),'-InstallDirectory',str(target)],
                capture_output=True,timeout=60,creationflags=flags)
            if removal.returncode:
                raise RuntimeError('Shipped uninstall wrapper failed: ' + removal.stderr.decode('utf-8', errors='replace'))
            assert not (target/'codex-usage-collector.exe').exists()
            assert (state/'config.json').exists()
            assert json.loads(settings.read_text()) == {'enabled':False,'scripts':{'user:other.js':False},'unrelated':42}
        finally:
            if (target/'codex-usage-collector.exe').exists():
                subprocess.run([str(target/'codex-usage-collector.exe'),'--state',str(state),'stop'],
                    capture_output=True,timeout=20,creationflags=flags)
                for attempt in range(40):
                    try:
                        (target/'codex-usage-collector.exe').unlink(missing_ok=True)
                        break
                    except PermissionError:
                        if attempt == 39:
                            raise
                        time.sleep(.25)
    print(json.dumps({'status':'passed','version':__version__,
        'checks':['actual-zip','verify','install','repeat-upgrade','preserve-config','private-token',
            'hidden-serve','shipped-powershell-uninstall','preserve-unrelated-settings','retain-data'],
        'bridgeProcessReplacement':'unit-tested with fake host; real host unchanged'}))


if __name__ == '__main__':
    main()
