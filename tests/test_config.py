import os
from pathlib import Path
from reference_guard.config import load_config


def test_relative_defaults_resolve_from_project_not_cwd(tmp_path, monkeypatch):
    root=tmp_path/'guard'; root.mkdir()
    (root/'config.toml').write_text("server_dir='../server'\nserver_python=''\n",encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    cfg=load_config(root)
    assert Path(cfg['server_dir'])==tmp_path/'server'
    suffix='Scripts/python.exe' if os.name=='nt' else 'bin/python'
    assert Path(cfg['server_python'])==tmp_path/'server'/'zotero-pdf2zh-next-venv'/suffix


def test_local_overrides_keep_other_defaults(tmp_path):
    (tmp_path/'config.toml').write_text("server_dir='../server'\nserver_python=''\nauto_skip_references=true\n",encoding='utf-8')
    (tmp_path/'config.local.toml').write_text("server_dir='custom/server'\nserver_python='custom/python'\n",encoding='utf-8')
    cfg=load_config(tmp_path)
    assert cfg['auto_skip_references'] is True
    assert Path(cfg['server_dir'])==tmp_path/'custom'/'server'
    assert Path(cfg['server_python'])==tmp_path/'custom'/'python'


def test_explicit_absolute_override_is_supported_without_publishing_it(tmp_path):
    server=tmp_path/'private-location'
    (tmp_path/'config.toml').write_text("server_dir='../server'\nserver_python=''\n",encoding='utf-8')
    (tmp_path/'config.local.toml').write_text('server_dir='+repr(server.as_posix())+'\n',encoding='utf-8')
    assert Path(load_config(tmp_path)['server_dir'])==server
