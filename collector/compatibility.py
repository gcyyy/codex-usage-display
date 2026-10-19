"""Local compatibility diagnostics; responses never contain paths or pairing secrets."""
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from . import __version__

ACTIONS = {
    'host_changed': ('Codex++ 程序与已安装桥接不一致，可能已被升级覆盖。', '安装匹配当前 Codex++ 版本的完整用量面板包，再热重载脚本；不要用旧桥接覆盖或降级。'),
    'host_missing': ('未找到安装记录中的 Codex++ 程序。', '确认 Codex++ 安装位置，再用匹配版本的安装包重新安装桥接。'),
    'host_unchecked': ('无法核验 Codex++ 桥接安装文件。', '在安装目录运行 Check-Compatibility.cmd；检查安装回执与文件读取权限。'),
    'collector_offline': ('无法连接采集器，尚未检查当天日志格式。', '先运行安装目录的 Start.cmd，再运行 Check-Compatibility.cmd。'),
    'authorization_failed': ('采集器拒绝当前配对。', '使用匹配版本的完整安装包重新配对，保留现有配置；不要公开配对令牌。'),
    'collector_protocol': ('采集器返回了不支持的格式。', '从同一版本完整包更新采集器和用户脚本，再热重载脚本。'),
    'log_adapter_required': ('当天存在尚未验证的 Codex 日志版本，Token 保留，相关金额暂不估算。', '更新支持这些日志版本的采集器。若暂无适配版，复制诊断摘要反馈；不要手工放宽版本检查或删除日志。'),
}


def issue(code):
    message, action = ACTIONS[code]
    return {'code': code, 'message': message, 'action': action}


def safe_version(value):
    return value if isinstance(value, str) and re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z.+_-]{0,79}', value) else 'unknown'


def log_compatibility(sessions, records, included):
    from .indexer import SUPPORTED_VERSIONS
    counts = Counter()
    for record in records:
        if included(record['sessionId']):
            counts[safe_version(sessions[record['sessionId']]['meta'].get('cli_version'))] += 1
    versions = [{'version': v, 'records': n, 'supported': v in SUPPORTED_VERSIONS} for v, n in sorted(counts.items())]
    unknown = any(not v['supported'] for v in versions)
    return {'schemaVersion': 1, 'collectorVersion': __version__,
            'logFormats': {'status': 'needs_adapter' if unknown else 'verified' if versions else 'no_records', 'versions': versions},
            'issues': [issue('log_adapter_required')] if unknown else []}


class HostCompatibility:
    """Hash at most once per minute, and only when file/receipt metadata changes."""
    def __init__(self, install_directory):
        self.root = Path(install_directory)
        self.checked_at = None
        self.signature = None
        self.cached = None

    def check(self):
        now = time.monotonic()
        if self.cached is not None and now - self.checked_at < 60:
            return dict(self.cached)
        self.checked_at = now
        try:
            receipt_path = self.root / 'installation.json'
            if not receipt_path.exists():
                self.signature = None
                self.cached = {'status': 'not_installed'}
                return dict(self.cached)
            receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
            host = Path(receipt['hostPath'])
            stat = host.stat()
            signature = (str(host), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, receipt['hostSHA256'])
            if signature != self.signature:
                with host.open('rb') as stream:
                    match = hashlib.file_digest(stream, 'sha256').hexdigest() == receipt['hostSHA256']
                self.cached = {'status': 'matches_installation' if match else 'changed'}
                self.signature = signature
        except FileNotFoundError:
            self.cached = {'status': 'missing'}
            self.signature = None
        except (OSError, ValueError, KeyError, TypeError):
            self.cached = {'status': 'unchecked'}
            self.signature = None
        return dict(self.cached)

    def enrich(self, report):
        report['host'] = self.check()
        code = {'changed': 'host_changed', 'missing': 'host_missing', 'unchecked': 'host_unchecked'}.get(report['host']['status'])
        report['issues'] = [x for x in report.get('issues', []) if not x['code'].startswith('host_')]
        if code:
            report['issues'].append(issue(code))
        report['status'] = 'attention' if report['issues'] else 'ok' if report['host']['status'] == 'matches_installation' else 'unchecked'
        return report

def check_installation(state, install_directory):
    """Works even if the renderer bridge is gone; never initializes or repairs files."""
    import urllib.error
    import urllib.request
    report = {'schemaVersion': 1, 'collectorVersion': __version__, 'collectorStatus': 'offline',
              'logFormats': {'status': 'unchecked', 'versions': []}, 'issues': []}
    try:
        config = json.loads((Path(state) / 'config.json').read_text(encoding='utf-8-sig'))
        port = config['port']
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('port')
        request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/today',
            headers={'Authorization': 'Bearer ' + config['pairingToken']})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=5) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('response')
        data = json.loads(raw)
        if data.get('schemaVersion') != '1' or not isinstance(data.get('compatibility'), dict):
            raise ValueError('schema')
        compatibility = data['compatibility']
        versions = compatibility['logFormats']['versions']
        if not isinstance(versions, list):
            raise ValueError('versions')
        report['logFormats'] = {'status': compatibility['logFormats']['status'],
            'versions': [{'version': safe_version(v['version']), 'records': int(v['records']),
                          'supported': v['supported'] is True} for v in versions]}
        if report['logFormats']['status'] not in ('verified', 'needs_adapter', 'no_records'):
            raise ValueError('status')
        report['collectorStatus'] = 'indexing' if data.get('dataStatus') == 'indexing' else 'connected'
        report['collectorVersion'] = safe_version(compatibility.get('collectorVersion'))
        if report['logFormats']['status'] == 'needs_adapter':
            report['issues'].append(issue('log_adapter_required'))
    except urllib.error.HTTPError as error:
        report['issues'].append(issue('authorization_failed' if error.code in (401, 403) else 'collector_offline'))
    except (OSError, urllib.error.URLError, KeyError, TypeError):
        report['issues'].append(issue('collector_offline'))
    except ValueError:
        report['issues'].append(issue('collector_protocol'))
    HostCompatibility(install_directory).enrich(report)
    if report['collectorStatus'] == 'indexing' and report['status'] == 'ok':
        report['status'] = 'indexing'
    return report
