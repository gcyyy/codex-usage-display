"""Local-only real-log benchmark. Writes counts/timings, never conversation text."""
import argparse
import json
import os
import platform
import statistics
import time
from pathlib import Path
from collector.aggregate import aggregate
from collector.indexer import Indexer
from collector.pricing import PriceBook
from collector.timeutil import utcnow


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--home",type=Path,default=Path(os.environ.get("CODEX_HOME",Path.home()/".codex")))
    parser.add_argument("--state",type=Path,default=Path(".runtime/benchmark"))
    parser.add_argument("--output",type=Path,default=Path("docs/benchmark.json"))
    args=parser.parse_args()
    index=Indexer(args.state/"index.sqlite3",[args.home])
    prices=PriceBook(Path(__file__).resolve().parent.parent/"pricing/official-standard.json")
    try:
        fresh=index.db.execute("SELECT COUNT(*) FROM files").fetchone()[0]==0
        started=time.perf_counter();index.scan_all();initial=time.perf_counter()-started
        sizes=[Path(p).stat().st_size for p in index.paths]
        durations=[]
        for _ in range(30):
            t=time.perf_counter();result=aggregate(index,prices);durations.append((time.perf_counter()-t)*1000)
        before=index.bytes_read;t=time.perf_counter();index.scan_all();steady=(time.perf_counter()-t)*1000
        result={"generatedAt":utcnow(),"platform":platform.platform(),"architecture":platform.machine(),"python":platform.python_version(),
                "files":len(sizes),"logBytes":sum(sizes),"freshIndex":fresh,"initialScanSeconds":initial,
                "summaryQueries":len(durations),"summaryMedianMs":statistics.median(durations),"summaryMaxMs":max(durations),
                "unchangedScanMs":steady,"unchangedScanReadBytes":index.bytes_read-before,
                "requestRecords":index.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
                "dataStatus":result["dataStatus"],"priceStatus":result["priceStatus"],
                "diagnosticCodes":[d["code"] for d in result["diagnostics"]],
                "scope":"local desktop and linked work subagents; no credentials read; no upload"}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False))
    finally:index.close()


if __name__=="__main__":main()
