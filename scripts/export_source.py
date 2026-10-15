"""Export only tracked public source; fail closed on local evidence and private paths."""
import hashlib
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from collector import __version__

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = {'local-installation.json','bridge-installation.json','bridge-backend-validation.json',
    'log-verification.json','image-pricing-verification.json','LOCAL_INSTALLATION.md','IMPLEMENTATION_SPEC.md'}


def public_files():
    names = subprocess.check_output(['git','ls-files','-z'], cwd=ROOT).decode('utf-8').split('\0')
    result = []
    for name in filter(None, names):
        path = PurePosixPath(name)
        if path.parts[0] in {'.reference','.runtime','.buildtools','build','dist','paired'} or path.name in PRIVATE or '__pycache__' in path.parts or path.suffix.lower() in {'.exe','.sqlite','.db','.pyc','.log'}:
            raise RuntimeError('Private or generated file tracked: ' + name)
        data = (ROOT/name).read_bytes()
        if re.search(rb'(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s]+', data):
            raise RuntimeError('Personal Windows path in public source: ' + name)
        result.append((name,data))
    if not result or 'LICENSE' not in {name for name,_ in result}:
        raise RuntimeError('Tracked public source and license required')
    return result


def main():
    files = public_files()
    output = ROOT/'dist'/f'codex-usage-display-{__version__}-source.zip'
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in files:
            info = zipfile.ZipInfo('codex-usage-display/'+name, date_time=(2026,10,15,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info,data)
    sums = ROOT/'dist/SHA256SUMS.txt'
    binary_name = f'codex-usage-display-{__version__}-windows-x64.zip'
    binary = ROOT/'dist'/binary_name
    if not binary.is_file():
        raise RuntimeError('Build the full binary bundle before exporting release source')
    sums.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in (binary,output)), encoding='utf-8')
    print(f'Public source exported: {len(files)} files; two release assets checksummed.')


if __name__ == '__main__':
    main()
