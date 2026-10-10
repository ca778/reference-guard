import json
import sys
import tomllib
from pathlib import Path
from reference_guard.detector import detect
from reference_guard.config import load_config

if __name__ == '__main__':
    config = load_config()
    print(json.dumps(detect(Path(sys.argv[1]).read_bytes(), config['max_detector_pages'],
                            config.get('reference_heading_aliases', [])).to_dict(), ensure_ascii=False, indent=2))
