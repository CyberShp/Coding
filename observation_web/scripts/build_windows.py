"""Assemble a Windows x64 portable package from tracked application files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = '3.13.12'
PYTHON_SHA256 = '76f238f606250c87c6beac75dccd35ee99070a13490555936abb6cb64ecce3d0'


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', '--short=12', 'HEAD'], cwd=PROJECT, text=True).strip()
    name = f'observation-platform-windows-x64-{revision}'
    with tempfile.TemporaryDirectory(prefix='observation-build-') as temporary:
        work = Path(temporary)
        package = work / name
        package.mkdir()
        files = subprocess.check_output(['git', 'ls-files', '-z', '--', 'backend', 'agent', 'alembic.ini', 'requirements.txt'], cwd=PROJECT).decode().split('\0')
        for entry in filter(None, files):
            relative = Path(entry)
            if any(part in {'tests', '__pycache__'} for part in relative.parts):
                continue
            if relative.suffix in {'.db', '.log', '.pyc', '.pem', '.key'} or entry in {'agent/config.json', 'agent/config.yaml'}:
                continue
            destination = package / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT / relative, destination)
        shutil.copytree(PROJECT / 'frontend' / 'dist', package / 'frontend' / 'dist')
        shutil.copy2(PROJECT / 'scripts' / 'portable_launcher.py', package / 'launch.py')
        config = json.loads((PROJECT / 'config.json.example').read_text(encoding='utf-8'))
        config['server'].update(host='127.0.0.1', debug=False)
        config['database'] = {'path': 'data/observation_web.db', 'echo': False}
        config['ai']['pem_cert_path'] = ''
        (package / 'data').mkdir()
        (package / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        (package / 'Start.bat').write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\n"%~dp0runtime\\python.exe" -X utf8 "%~dp0launch.py"\r\nif errorlevel 1 pause\r\n')
        shutil.copy2(PROJECT / 'docs' / 'WINDOWS_PORTABLE.md', package / 'README.md')
        runtime = package / 'runtime'
        runtime.mkdir()
        archive = work / 'python.zip'
        urllib.request.urlretrieve(f'https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip', archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != PYTHON_SHA256:
            raise RuntimeError('Python download checksum mismatch')
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(runtime)
        (runtime / 'python313._pth').write_text('python313.zip\n.\nLib/site-packages\n..\nimport site\n', encoding='ascii')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', '--target', str(runtime / 'Lib' / 'site-packages'), '-r', str(PROJECT / 'requirements.txt')], check=True)
        subprocess.run([str(runtime / 'python.exe'), '-X', 'utf8', '-c', 'import fastapi, uvicorn, paramiko, sqlalchemy, aiosqlite, alembic, backend.main'], cwd=package, check=True)
        manifest = subprocess.check_output([sys.executable, '-m', 'pip', 'list', '--path', str(runtime / 'Lib' / 'site-packages'), '--format=json'], text=True)
        (package / 'BUILD.json').write_text(json.dumps({'revision': revision, 'python': PYTHON_VERSION, 'dependencies': json.loads(manifest)}, indent=2), encoding='utf-8')
        # Run acceptance on an extracted copy; its generated DB/logs stay out of ZIP.
        zip_path = Path(shutil.make_archive(str(output / name), 'zip', work, name))
        subprocess.run([sys.executable, str(PROJECT / 'scripts' / 'smoke_windows.py'), str(zip_path)], check=True)
        digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        zip_path.with_suffix('.zip.sha256').write_text(f'{digest}  {zip_path.name}\n', encoding='ascii')
        print(f'Portable package: {zip_path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=PROJECT / 'dist')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Windows x64 build environment required')
    build(args.output.resolve())
