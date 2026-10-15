import hashlib
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from collector import __version__
from collector.install import install, uninstall, verify_package, Transaction, checksum, json_bytes


class InstallationTest(unittest.TestCase):
    def setUp(self):
        output = Path(__file__).resolve().parent / 'output'
        output.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=output)
        self.root = Path(self.temp.name)
        self.package = self.root / 'package'
        self.target = self.root / 'installed'
        self.plus = self.root / 'Codex++'
        self.host = self.root / 'host/codex-plus-plus.exe'
        self.host.parent.mkdir()
        self.host.write_bytes(b'original-host')
        self.plus.mkdir()
        self.settings = self.plus / 'user_scripts.json'
        self.settings.write_bytes(json_bytes({'enabled':False,'scripts':{'user:unrelated.js':False},'other':42}))
        self.args = Namespace(package_root=self.package, install_dir=self.target,
            codex_plus_dir=self.plus, host_exe=self.host, host_state=self.root / 'host-state', install_bridge=True)
        data = {'codex-usage-collector.exe':b'collector', 'userscript/codex-usage-status.js':b'const config = /*__PAIRING_CONFIG__*/null;',
            'pricing/official-standard.json':b'{}','LICENSE':b'license', 'release.json':json_bytes({'schemaVersion':1,'version':__version__,'bundleBridge':True}),
            'bridge/codex-plus-plus.exe':b'patched-host', 'bridge/corresponding-source.zip':b'public-source',
            'bridge/build.json':json_bytes({'sha256':hashlib.sha256(b'patched-host').hexdigest(),
                'compatibleHostSHA256':[checksum(self.host)]})}
        self.package.mkdir()
        for name, content in data.items():
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.manifest = {name:hashlib.sha256(content).hexdigest() for name,content in data.items()}
        self.save_manifest()
        self.patches = [patch('collector.install.' + name) for name in ('run','start','stop_manager','start_manager')]
        self.mocks = [p.start() for p in self.patches]
        self.mocks[0].side_effect = self.command

    def command(self, exe, *args):
        if args[-1] == 'init':
            state = Path(args[1]);state.mkdir(parents=True, exist_ok=True)
            if not (state / 'config.json').exists():
                (state / 'config.json').write_bytes(json_bytes({'port':48763,'pairingToken':'a'*43,'homes':['synthetic-home']}))
        return b'{}'

    def save_manifest(self):
        (self.package / 'SHA256SUMS.json').write_bytes(json_bytes(self.manifest))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_full_install_upgrade_preserves_config_and_unrelated_settings(self):
        install(self.args)
        config = (self.target / '.runtime/config.json').read_bytes()
        install(self.args)
        self.assertEqual((self.target / '.runtime/config.json').read_bytes(), config)
        settings = json.loads(self.settings.read_text())
        self.assertEqual(settings['scripts']['user:unrelated.js'], False)
        self.assertEqual(settings['other'], 42)
        self.assertEqual(self.host.read_bytes(), b'patched-host')
        self.assertNotIn('a'*43, (self.plus / 'user_scripts/codex-usage-status.js').read_text())
        self.assertEqual(self.mocks[2].call_count, 1)

    def test_hash_failure_and_unknown_host_leave_everything_untouched(self):
        (self.package / 'LICENSE').write_bytes(b'changed')
        before = self.settings.read_bytes()
        with self.assertRaisesRegex(ValueError, 'checksum'):
            install(self.args)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.settings.read_bytes(), before)
        (self.package / 'LICENSE').write_bytes(b'license')
        self.host.write_bytes(b'unknown-host')
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            install(self.args)
        self.assertFalse(self.target.exists())

    def test_traversal_and_private_payload_are_rejected(self):
        for name in ('../outside', 'C:/outside', 'docs/../../outside', '.runtime/config.json', 'installation.json'):
            with self.subTest(name=name):
                self.manifest[name] = 'a'*64
                self.save_manifest()
                with self.assertRaises(ValueError):
                    verify_package(self.package)
                del self.manifest[name]

    def test_failed_start_rolls_back_host_script_settings_and_collector(self):
        before = self.settings.read_bytes()
        self.mocks[1].side_effect = RuntimeError('synthetic startup failure')
        with self.assertRaisesRegex(RuntimeError, 'synthetic'):
            install(self.args)
        self.assertEqual(self.host.read_bytes(), b'original-host')
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertFalse((self.target / 'codex-usage-collector.exe').exists())
        self.assertFalse((self.plus / 'user_scripts/codex-usage-status.js').exists())

    def test_uninstall_restores_original_host_and_keeps_data(self):
        before = self.settings.read_bytes()
        install(self.args)
        config = (self.target / '.runtime/config.json').read_bytes()
        uninstall(self.args)
        self.assertEqual(self.host.read_bytes(), b'original-host')
        self.assertEqual(json.loads(self.settings.read_text()), json.loads(before))
        self.assertEqual((self.target / '.runtime/config.json').read_bytes(), config)
        self.assertFalse((self.target / 'codex-usage-collector.exe').exists())

    def test_failed_first_install_can_be_retried_with_recovery_directories_present(self):
        self.mocks[1].side_effect = RuntimeError('synthetic startup failure')
        with self.assertRaises(RuntimeError):
            install(self.args)
        self.mocks[1].side_effect = None
        install(self.args)
        self.assertTrue((self.target / 'installation.json').is_file())

    def test_unrelated_install_directory_is_rejected_before_writes(self):
        self.target.mkdir()
        private = self.target/'unrelated.txt';private.write_text('keep')
        with self.assertRaisesRegex(ValueError, 'unrelated'):
            install(self.args)
        self.assertEqual(private.read_text(), 'keep')

    def test_uninstall_keeps_modified_files_and_new_unrelated_settings(self):
        install(self.args)
        script = self.plus / 'user_scripts/codex-usage-status.js'
        script.write_text('user changed this')
        settings = json.loads(self.settings.read_text());settings['scripts']['user:new.js'] = True
        self.settings.write_bytes(json_bytes(settings))
        self.host.write_bytes(b'newer-host-installed-by-user')
        uninstall(self.args)
        self.assertEqual(script.read_text(), 'user changed this')
        self.assertTrue(json.loads(self.settings.read_text())['scripts']['user:new.js'])
        self.assertEqual(self.host.read_bytes(), b'newer-host-installed-by-user')

    def test_transaction_recovery_journal_restores_existing_and_removes_new_file(self):
        existing = self.root / 'existing';existing.write_bytes(b'old')
        new = self.root / 'new'
        tx = Transaction(self.root / 'backup')
        tx.write(existing, b'new');tx.write(new, b'new')
        tx.rollback()
        self.assertEqual(existing.read_bytes(), b'old')
        self.assertFalse(new.exists())

    def test_release_version_and_source_required(self):
        meta = self.package / 'release.json'
        meta.write_bytes(json_bytes({'schemaVersion':1,'version':'wrong'}))
        self.manifest['release.json'] = checksum(meta);self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'version'):
            verify_package(self.package)
        meta.write_bytes(json_bytes({'schemaVersion':1,'version':__version__,'bundleBridge':True}))
        self.manifest['release.json'] = checksum(meta)
        del self.manifest['bridge/corresponding-source.zip'];self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'source'):
            verify_package(self.package)


if __name__ == '__main__':
    unittest.main()
