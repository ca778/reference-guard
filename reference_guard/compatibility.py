from __future__ import annotations
import hashlib
import json
import re
import subprocess
from pathlib import Path
from .config import ROOT


def fingerprint(config: dict) -> dict:
    server = Path(config['server_dir'])
    paths = [server / 'server.py', *sorted((server / 'utils').glob('*.py'))]
    metadata = subprocess.run([config['server_python'], '-c',
        "import importlib.metadata as m,json; print(json.dumps({x:m.version(x) for x in ['pdf2zh-next','BabelDOC','PyMuPDF']}))"],
        capture_output=True, text=True, check=True, timeout=30)
    packages = Path(config['server_python']).parents[1] / 'Lib' / 'site-packages'
    paths += sorted((packages / 'babeldoc').rglob('*.py'))
    paths += sorted((packages / 'pdf2zh_next').rglob('*.py'))
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    source = (server / 'server.py').read_text(encoding='utf-8')
    version = re.search(r'__version__\s*=\s*[\u0022\u0027]([^\u0022\u0027]+)', source)
    required = ['fileContent', 'fileName', 'skip_last_pages', "'--pages'", "'/translate'", "'/events'", '--port']
    cfg = (server / 'utils' / 'config.py').read_text(encoding='utf-8')
    format_ok = all(t in source for t in required) and all(t in cfg for t in ['skipLastPages', 'onlyIncludeTranslatedPage', "pdf_config['only_include_translated_page']"])
    return {'server_version': version[1] if version else 'UNKNOWN', 'packages': json.loads(metadata.stdout), 'source_hashes': hashes, 'format_ok': format_ok}


def auto_allowed(config: dict) -> tuple[bool, str]:
    try:
        current = fingerprint(config)
        validation = json.loads((ROOT / config['validation_file']).read_text(encoding='utf-8'))
        if not current['format_ok'] or validation.get('fingerprint') != current:
            return False, '接口、源码或依赖版本变化：自动跳页关闭，请重新验收'
        if not all(validation.get('modes', {}).get(m) == 'PASS' for m in ['mono', 'dual_lr', 'dual_alternating']):
            return False, '输出完整性尚未全部通过：自动跳页关闭'
        return True, '已匹配本地源码、版本及输出验收记录'
    except Exception:
        return False, '缺少兼容性验收记录或检查失败：自动跳页关闭'
