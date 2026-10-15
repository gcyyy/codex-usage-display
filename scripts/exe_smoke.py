"""Test the shipped EXE on synthetic local files and its own HTTP port."""
import argparse
import json
import os
import socket
import subprocess
import time
import urllib.request
from decimal import Decimal
from datetime import timedelta
from pathlib import Path
from tests.fixtures.factory import meta, context, count, usage, write, response as response_event
from collector import __version__
from collector.timeutil import window, parse_time

ROOT=Path(__file__).resolve().parent.parent


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--exe",type=Path,default=ROOT/"dist"/"codex-usage-collector.exe")
    args=parser.parse_args()
    state=ROOT/".runtime"/"exe-smoke"
    home=state/"中文 home with spaces"
    day,start,_=window()
    moment=parse_time(start)+timedelta(hours=1)
    data=usage(100000,60000,0,10000,4000)
    write(home/"sessions"/"2026"/"10"/"13"/"s.jsonl",[meta(),context(ts=(moment-timedelta(seconds=1)).isoformat()),
        response_event(value=data,ts=moment.isoformat()),count(data,data,ts=moment.isoformat()),
        response_event(value=data,ts=(moment+timedelta(seconds=1)).isoformat())])
    def run(*parts,expected=0):
        proc=subprocess.run([str(args.exe),"--state",str(state),*parts],capture_output=True,timeout=30)
        if proc.returncode!=expected:raise AssertionError(f"EXE command {parts[0]} failed (exit {proc.returncode})")
        return proc
    run("--home",str(home),"init")
    config=json.loads((state/"config.json").read_text(encoding="utf-8"))
    with socket.socket() as sock:sock.bind(("127.0.0.1",0));config["port"]=sock.getsockname()[1]
    (state/"config.json").write_text(json.dumps(config),encoding="utf-8")
    run("snapshot","--date",day,"--output",str(state/"result.json"))
    result=json.loads((state/"result.json").read_text(encoding="utf-8"))
    assert result["totals"]["total"]==110000 and Decimal(result["totalCostUSD"])==Decimal("0.186")
    run("pair","--output",str(state/"paired.js"))
    assert '/*__PAIRING_CONFIG__*/null' not in (state/"paired.js").read_text(encoding="utf-8")
    run("pair","--transport","bridge","--output",str(state/"bridge.js"))
    assert config['pairingToken'] not in (state/"bridge.js").read_text(encoding='utf-8')
    process=subprocess.Popen([str(args.exe),"--state",str(state),"serve"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if process.poll() is not None:raise AssertionError("EXE service exited")
            if (state/"service.json").exists():break
            time.sleep(.1)
        else:raise AssertionError("EXE service not ready")
        run("diagnose")
        run("snapshot",expected=1)  # Same state may not mutate while service holds instance lock.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request=urllib.request.Request(f"http://127.0.0.1:{config['port']}/v1/today",headers={"Authorization":"Bearer "+config["pairingToken"]})
        with opener.open(request,timeout=3) as response:assert json.loads(response.read())["totals"]["total"]==110000
        run("stop");assert process.wait(timeout=10)==0
        assert not (state/"service.json").exists()
        run("rebuild","--date",day,"--output",str(state/"rebuilt.json"))
        assert Decimal(json.loads((state/"rebuilt.json").read_text(encoding="utf-8"))["totalCostUSD"])==Decimal("0.186")
    finally:
        if process.poll() is None:
            (state/"stop.request").touch()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
    output={"status":"passed","version":__version__,"commands":["init","snapshot","native-response-dedup","pair","pair-bridge","serve-hidden","diagnose","single-instance","today","stop","rebuild"],
            "environment":"Windows x64 executable / synthetic fixtures / own temporary loopback port"}
    (ROOT/"docs"/"exe-smoke.json").write_text(json.dumps(output,indent=2),encoding="utf-8")
    print(json.dumps(output))


if __name__=="__main__":main()
