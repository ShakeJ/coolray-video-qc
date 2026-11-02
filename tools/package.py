#!/usr/bin/env python3
"""Build a deterministic allowlisted ZIP without uploading or Git history."""
from pathlib import Path
import hashlib
import re
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'SKILL.md', 'README.md', 'README.ko.md', 'LICENSE', 'VERSION',
    '.gitignore', '.gitattributes', 'agents/openai.yaml',
    'scripts/media_audit.py', 'scripts/captions.py',
    'references/reports.md', 'examples/clean.srt', 'examples/overlap.srt',
    'examples/make_demo.py', 'examples/clean.en.srt', 'tests/test_qc.py', 'tools/package.py',
    '.github/workflows/ci.yml',
]


def main():
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('VERSION must be numeric MAJOR.MINOR.PATCH')
    for name in FILES:
        p = ROOT / name
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(ROOT):
            raise ValueError('Missing, symlinked or invalid release member: ' + name)
        if p.suffix == '.py':
            compile(p.read_text(encoding='utf-8'), name, 'exec')
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    target = out / f'coolray-video-qc-{version}.zip'
    temp = target.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted(FILES):
                info = zipfile.ZipInfo('coolray-video-qc/' + name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, (ROOT / name).read_bytes())
        with zipfile.ZipFile(temp) as archive:
            if archive.testzip():
                raise ValueError('Corrupt archive')
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (out / 'SHA256SUMS').write_text(f'{digest}  {target.name}\n', encoding='utf-8')
    print(f'{target.name}: {target.stat().st_size} bytes, {len(FILES)} files')


if __name__ == '__main__':
    main()
