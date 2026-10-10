import json
from pathlib import Path
from unittest.mock import patch
from reference_guard.compatibility import auto_allowed
from tests.test_proxy import CONFIG


def test_version_or_source_change_disables(tmp_path):
    cfg={**CONFIG,'validation_file':str(tmp_path/'validation.json')}
    tested={'server_version':'4.1.7','format_ok':True}
    Path(cfg['validation_file']).write_text(json.dumps({'fingerprint':tested,'modes':{m:'PASS' for m in ['mono','dual_lr','dual_alternating']}}))
    with patch('reference_guard.compatibility.fingerprint',return_value=tested):
        assert auto_allowed(cfg)[0]
    with patch('reference_guard.compatibility.fingerprint',return_value={**tested,'server_version':'5.0'}):
        assert not auto_allowed(cfg)[0]


def test_missing_validation(tmp_path):
    with patch('reference_guard.compatibility.fingerprint',return_value={}):
        assert not auto_allowed({**CONFIG,'validation_file':str(tmp_path/'missing.json')})[0]
