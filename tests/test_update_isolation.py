import os
import subprocess
import pytest
from pathlib import Path
from tests.test_proxy import CONFIG


def test_actual_official_sync_only_touches_server_tree(tmp_path):
    if not Path(CONFIG['server_python']).is_file() or not (Path(CONFIG['server_dir'])/'utils'/'auto_update.py').is_file():
        pytest.skip('Optional official Server installation is not available')
    source=tmp_path/'downloaded'; source.mkdir()
    server=tmp_path/'pdf2zh'/'server'; server.mkdir(parents=True)
    guard=server.parent/'reference-guard'; guard.mkdir()
    (guard/'sentinel.py').write_text('guard must survive')
    (source/'server.py').write_text('new official source')
    (server/'server.py').write_text('old official source')
    backup=tmp_path/'backup'
    snippet="from utils.auto_update import smart_file_sync; import sys; stats={'unchanged':0,'updated':0,'new':0}; smart_file_sync(sys.argv[1],sys.argv[2],stats,sys.argv[3],[],[])"
    completed=subprocess.run([CONFIG['server_python'],'-c',snippet,str(source),str(server),str(backup)],
        cwd=CONFIG['server_dir'],capture_output=True,timeout=20,
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    assert completed.returncode==0
    assert (server/'server.py').read_text()=='new official source'
    assert (guard/'sentinel.py').read_text()=='guard must survive'
    assert (backup/'server.py').read_text()=='old official source'
