import argparse
import json
import os
import secrets
import sqlite3
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from . import __version__
from .aggregate import aggregate
from .indexer import Indexer
from .pricing import PriceBook
from .service import CollectorService


def bundle_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def app_root():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def config_at(state):
    path = state / "config.json"
    if not path.exists():
        home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
        config = {"schemaVersion": "1", "homes": [home], "timezone": "Asia/Shanghai", "port": 48763,
                  "allowedOrigins": ["app://-"], "pairingToken": secrets.token_urlsafe(32)}
        state.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    config = json.loads(path.read_text(encoding="utf-8"))
    if type(config["port"]) is not int or not 1024 <= config["port"] <= 65535 or len(config["pairingToken"]) < 32:
        raise ValueError("Invalid service configuration")
    if not config["homes"] or not isinstance(config["homes"], list) or any(not isinstance(h, str) for h in config["homes"]):
        raise ValueError("Invalid homes")
    if not isinstance(config["allowedOrigins"], list) or any(o in ("*", "null") or not isinstance(o, str) for o in config["allowedOrigins"]):
        raise ValueError("Explicit non-null origins required")
    return config


@contextmanager
def instance_lock(state):
    stream = (state / "instance.lock").open("a+b")
    stream.seek(0)
    if stream.read(1) == b"":
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError("Collector already running; stop before offline scan/rebuild")
    try:
        yield
    finally:
        stream.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="本机 Codex 当日 Token / API 等价估算")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--state", type=Path, default=app_root() / ".runtime")
    parser.add_argument("--home", action="append", help="明确配置 Codex home，可重复指定")
    parser.add_argument("--prices", type=Path, default=None)
    parser.add_argument("command", choices=("init", "serve", "stop", "diagnose", "rebuild", "snapshot", "pair", "install", "uninstall", "verify-package", "compatibility-check"))
    parser.add_argument("--package-root", type=Path, default=app_root())
    parser.add_argument("--install-dir", type=Path)
    parser.add_argument("--codex-plus-dir", type=Path)
    parser.add_argument("--host-exe", type=Path)
    parser.add_argument("--host-state", type=Path)
    parser.add_argument("--install-bridge", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--date")
    parser.add_argument("--transport", choices=("http", "bridge"), default="http", help="bridge 需要宿主实现公开的 usage-status 路由")
    parser.add_argument("--mount-selector", help="兼容旧版本参数；0.1.1 的标题栏停靠模式不使用此选项")
    args = parser.parse_args(argv)
    if args.command in ('install', 'uninstall', 'verify-package'):
        from . import install as setup
        try:
            if args.command == 'verify-package':
                manifest, metadata = setup.verify_package(args.package_root)
                print(json.dumps({'status':'verified','version':metadata['version'],'files':len(manifest)}))
            elif os.name != 'nt':
                raise ValueError('Installation supports Windows only')
            else:
                getattr(setup, args.command)(args)
            return 0
        except (ValueError, RuntimeError) as error:
            print('Installation: ' + str(error), file=sys.stderr)
            return 1
        except (OSError, KeyError, TypeError):
            print('Installation failed. Check package, permissions and local configuration.', file=sys.stderr)
            return 1
    if args.command == "compatibility-check":
        from .compatibility import check_installation
        report = check_installation(args.state.resolve(), app_root())
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True))
        return 0 if report["status"] == "ok" else 1
    state = args.state.resolve()
    try:
        config = config_at(state)
        if args.home:
            config["homes"] = args.home
        if args.command == "init":
            if args.home:
                (state / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
            print("Configuration initialized (pairing token kept local).")
            return 0
        if args.command == "pair":
            source = (bundle_root() / "userscript" / "usage-status.js").read_text(encoding="utf-8")
            pairing = {"transport": args.transport}
            if args.transport == "http":
                pairing.update(endpoint=f"http://127.0.0.1:{config['port']}", token=config["pairingToken"])
            if args.mount_selector:
                pairing["mountSelector"] = args.mount_selector
            paired = source.replace('/*__PAIRING_CONFIG__*/null', json.dumps(pairing))
            output = args.output or app_root() / "dist" / "paired" / "codex-usage-status.js"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(paired, encoding="utf-8")
            print("Paired user script generated. Treat it as private; do not publish it.")
            return 0
        if args.command == "stop":
            (state / "stop.request").touch()
            deadline = time.monotonic() + 10
            while (state / "service.json").exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            if (state / "service.json").exists():
                raise RuntimeError("Stop timed out; collector may still be running")
            print("Collector stopped.")
            return 0
        if args.command == "diagnose":
            request = urllib.request.Request(f"http://127.0.0.1:{config['port']}/v1/health", headers={"Authorization": "Bearer " + config["pairingToken"]})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=3) as response:
                print(response.read().decode())
            return 0
        with instance_lock(state):
            prices = PriceBook(args.prices or app_root() / "pricing" / "official-standard.json", state / "prices.last-good.json")
            # Bundled snapshot fallback when executable moved alone.
            if prices.table is None and args.prices is None:
                local_table_invalid = (app_root() / "pricing" / "official-standard.json").exists()
                prices = PriceBook(bundle_root() / "pricing" / "official-standard.json", state / "prices.last-good.json")
                if local_table_invalid:
                    prices.error = "invalid_price_table"
            index = Indexer(state / "usage.sqlite3", config["homes"])
            try:
                index.price_version(prices.table["priceVersion"] if prices.table else None)
                if args.command == "serve":
                    (state / "stop.request").unlink(missing_ok=True)
                    from .compatibility import HostCompatibility
                    CollectorService(index, prices, config, HostCompatibility(app_root())).serve(state / "stop.request", state / "service.json")
                else:
                    if args.command == "rebuild":
                        index.rebuild()
                    index.scan_all()
                    result = aggregate(index, prices, config["timezone"], args.date)
                    result["performance"] = {"files": len(index.paths), "indexedBytes": index.bytes_read}
                    encoded = json.dumps(result, indent=2, ensure_ascii=False)
                    if args.output:
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        args.output.write_text(encoded, encoding="utf-8")
                    else:
                        print(encoded)
            finally:
                index.close()
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error):
        # Do not leak user paths or tokens through a generic diagnostic error.
        print("Command failed. Check configuration, permissions, port and running instance.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
