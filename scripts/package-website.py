"""Package standalone website source and CI, excluding secrets and runtime data."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / 'website'
VERSION = '37'


def source_files():
    excluded = {'.git', '.venv', '__pycache__', '.pytest_cache', 'secrets'}
    files = {}
    for path in WEBSITE.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(WEBSITE)
        if any(part in excluded for part in relative.parts):
            continue
        if relative.parts[0] in ('data', 'backups') and path.name != '.gitkeep':
            continue
        if path.name != '.env.example' and (path.name == '.env' or path.name.startswith('.env.')):
            continue
        if ('.sqlite3' in path.name or path.suffix in ('.pyc','.pyo','.bak','.log','.zip')):
            continue
        files[relative.as_posix()] = path.read_bytes()
    workflow = (ROOT / '.github/workflows/website.yml').read_text()
    workflow = workflow.replace("paths: ['website/**', '.github/workflows/website.yml']", "paths: ['**']")
    workflow = workflow.replace('working-directory: website', 'working-directory: .')
    workflow = workflow.replace('website/requirements-', 'requirements-')
    files['.github/workflows/website.yml'] = workflow.encode()
    manifest = {'version': VERSION, 'files': {name:hashlib.sha256(data).hexdigest()
                 for name,data in sorted(files.items())}}
    files['RELEASE_MANIFEST.json'] = (json.dumps(manifest, indent=2)+'\n').encode()
    return files


def package(output):
    files = source_files()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, contents in sorted(files.items()):
            entry = ZipInfo(f'chess-fantasy-league-v{VERSION}/{name}', (2026,10,9,0,0,0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, contents)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(f'{digest}  {output.name}\n')
    print(f'{len(files)} files: {output}')
    print(f'SHA-256: {digest}')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/f'build/chess-fantasy-league-v{VERSION}.zip')
    package(parser.parse_args().output)
