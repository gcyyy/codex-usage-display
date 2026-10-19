import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from collector.indexer import Indexer
from collector.pricing import PriceBook
from collector.service import CollectorService
from tests.fixtures.factory import meta, context, count, write

ROOT = Path(__file__).resolve().parent.parent


class ServiceTest(unittest.TestCase):
    def setUp(self):
        (ROOT/"tests"/"output").mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/"tests"/"output")
        home=Path(self.tmp.name)/"home"
        stamp = datetime.now(timezone.utc).isoformat()
        write(home/"sessions"/"s.jsonl",[meta(),context(ts=stamp),count(ts=stamp)])
        self.index=Indexer(Path(self.tmp.name)/"index.sqlite",[home]);self.index.scan_all()
        config={"port":0,"timezone":"Asia/Shanghai","pairingToken":"x"*48,"allowedOrigins":["app://-","http://127.0.0.1:48000"]}
        self.service=CollectorService(self.index,PriceBook(ROOT/"pricing"/"official-standard.json"),config)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),self.service.handler())
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.index.close();self.tmp.cleanup()

    def get(self,path="/v1/today",headers=None,method="GET"):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
        conn.request(method,path,headers=headers or {})
        response=conn.getresponse();data=response.read()
        result=response.status,dict(response.getheaders()),json.loads(data) if data else None
        conn.close();return result

    def auth(self,**extra):return {"Authorization":"Bearer "+"x"*48,**extra}

    def test_authorized_contract_no_private_paths(self):
        code,headers,body=self.get(headers=self.auth(Origin="app://-"))
        self.assertEqual(code,200);self.assertEqual(body["totals"]["total"],110)
        self.assertEqual(headers["Access-Control-Allow-Origin"],"app://-")
        self.assertNotIn(self.tmp.name,json.dumps(body));self.assertNotIn("sessionId",json.dumps(body))
        self.assertEqual(self.get("/v1/health",self.auth())[0],200)

    def test_compatibility_report_and_local_cli_check_are_secret_free(self):
        from collector.compatibility import HostCompatibility, check_installation
        import hashlib
        root = Path(self.tmp.name)
        host = root / 'host.exe'; host.write_bytes(b'host')
        (root / 'installation.json').write_text(json.dumps({'hostPath': str(host),
            'hostSHA256': hashlib.sha256(host.read_bytes()).hexdigest()}))
        state = root / 'state'; state.mkdir()
        (state / 'config.json').write_text(json.dumps({**self.service.config, 'port': self.server.server_port}))
        self.service.compatibility = HostCompatibility(root)
        report = check_installation(state, root)
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['collectorStatus'], 'connected')
        self.assertEqual(report['logFormats']['status'], 'verified')
        self.assertNotIn('x' * 48, json.dumps(report))
        self.assertNotIn(str(root), json.dumps(report))

    def test_random_webpage_no_token_and_null_origin_denied(self):
        for headers in [{},{"Origin":"https://evil.invalid"},self.auth(Origin="https://evil.invalid"),self.auth(Origin="null"),self.auth(Origin="file://")]:
            code,response,_=self.get(headers=headers)
            self.assertEqual(code,403);self.assertNotIn("Access-Control-Allow-Origin",response)

    def test_host_dns_rebinding_and_wrong_token(self):
        self.assertEqual(self.get(headers=self.auth(Host="evil.invalid"))[0],403)
        self.assertEqual(self.get(headers={"Authorization":"Bearer wrong"})[0],403)

    def test_readonly_no_file_selection(self):
        self.assertEqual(self.get("/v1/today?path=C:/private",self.auth())[0],400)
        self.assertEqual(self.get("/v1/today?includeInternal=true&includeInternal=false",self.auth())[0],400)
        self.assertEqual(self.get("/v1/today?includeInternal=true",self.auth())[0],200)
        self.assertEqual(self.get("/v1/today",self.auth(),"POST")[0],405)
        self.assertEqual(self.get("/auth.json",self.auth())[0],404)

    def test_preflight_explicit_origin_method_and_header(self):
        headers={"Origin":"app://-","Access-Control-Request-Method":"GET","Access-Control-Request-Headers":"authorization"}
        self.assertEqual(self.get(headers=headers,method="OPTIONS")[0],204)
        headers["Origin"]="https://evil.invalid"
        self.assertEqual(self.get(headers=headers,method="OPTIONS")[0],403)

    def test_refresh_coalesces_and_overlapping_scan_rejected(self):
        for _ in range(20):self.service.refresh()
        self.assertTrue(self.service.wake.is_set())
        self.index.scan_lock.acquire()
        try:self.assertFalse(self.index.scan())
        finally:self.index.scan_lock.release()

    def test_cancelled_client_does_not_destroy_index(self):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
        conn.request("GET","/v1/today",headers=self.auth());conn.close()
        self.assertEqual(self.get(headers=self.auth())[2]["totals"]["total"],110)


if __name__=="__main__":unittest.main()
