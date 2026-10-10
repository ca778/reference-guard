"""Isolated bounded PDF parser: stdout is structured evidence, never original text."""
import base64
import json
import sys
from .detector import detect

if __name__ == '__main__':
    request = json.load(sys.stdin)
    try:
        result = detect(base64.b64decode(request['pdf'], validate=True), request['max_pages'], request.get('extra_headings', [])).to_dict()
        print(json.dumps(result))
    except Exception:
        print(json.dumps({'detection_status': 'FALLBACK', 'skip_last_pages': 0, 'reason': 'PDF parsing failed'}))
