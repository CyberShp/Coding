"""Validate the extracted portable runtime, HTTP UI/API and DB restart."""
import json
from contextlib import closing
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


def check(archive):
    with tempfile.TemporaryDirectory(prefix='observation smoke ') as directory:
        root = Path(directory) / '观察点 平台'
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(root)
        package = next(root.iterdir())
        config_path = package / 'config.json'
        config = json.loads(config_path.read_text(encoding='utf-8'))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        config['server']['port'] = port
        config_path.write_text(json.dumps(config), encoding='utf-8')
        url = f'http://127.0.0.1:{port}'
        def get(path):
            with urllib.request.urlopen(url + path, timeout=3) as response:
                return response.read()
        database = package / 'data' / 'observation_web.db'
        for attempt in range(2):
            with open(Path(directory) / 'server.log', 'w', encoding='utf-8') as log:
                process = subprocess.Popen([str(package / 'runtime' / 'python.exe'), '-X', 'utf8', str(package / 'launch.py'), '--no-browser'], cwd=directory, stdout=log, stderr=subprocess.STDOUT)
                try:
                    for _ in range(120):
                        if process.poll() is not None:
                            raise RuntimeError('Portable server exited')
                        try:
                            assert json.loads(get('/readyz'))['status'] == 'ready'
                            break
                        except Exception:
                            time.sleep(0.5)
                    else:
                        raise RuntimeError('Portable server readiness timeout')
                    html = get('/').decode()
                    assert '<html' in html
                    assert get('/topology') == get('/')
                    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
                    assert assets, 'Built assets missing'
                    for asset in assets:
                        assert len(get(asset)) > 0
                    assert isinstance(json.loads(get('/api/topology')), dict)
                    assert database.is_file()
                    with closing(sqlite3.connect(database)) as db:
                        assert db.execute('select version_num from alembic_version').fetchone()
                        if attempt == 0:
                            db.execute('create table portable_smoke (value text)')
                            db.execute("insert into portable_smoke values ('retained')")
                            db.commit()
                        else:
                            assert db.execute('select value from portable_smoke').fetchone()[0] == 'retained'
                except Exception:
                    log.flush()
                    print((Path(directory) / 'server.log').read_text(encoding='utf-8'))
                    raise
                finally:
                    process.terminate()
                    process.wait(timeout=20)
        print('PASS: extracted runtime, Unicode path, UI/assets, topology API, migrations, DB restart')


if __name__ == '__main__':
    check(Path(sys.argv[1]))
