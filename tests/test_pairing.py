import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from collector.cli import main


class PairingTest(unittest.TestCase):
    def test_bridge_script_keeps_token_in_backend(self):
        root = Path(__file__).resolve().parent / 'output'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            state = Path(temporary)
            token = 'synthetic_pairing_token_' + 'x' * 32
            (state / 'config.json').write_text(json.dumps({
                'homes': [str(state / 'synthetic-home')], 'port': 48763,
                'pairingToken': token, 'allowedOrigins': ['app://-'], 'timezone': 'Asia/Shanghai',
            }), encoding='utf-8')
            for transport in ('bridge', 'http'):
                output = state / (transport + '.js')
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['--state', str(state), 'pair', '--transport', transport,
                                           '--output', str(output)]), 0)
                script = output.read_text(encoding='utf-8')
                self.assertEqual(token in script, transport == 'http')
                self.assertNotIn('/*__PAIRING_CONFIG__*/null', script)


if __name__ == '__main__':
    unittest.main()
