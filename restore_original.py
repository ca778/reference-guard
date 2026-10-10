"""Launch the unmodified official Server directly, without the Guard proxy."""
import subprocess
from launcher import port_free
from reference_guard.config import load_config

if __name__ == '__main__':
    config = load_config()
    if not port_free(config['listen_port']):
        raise SystemExit('Port occupied: close the current Guard/Server window first')
    try:
        raise SystemExit(subprocess.call([config['server_python'], 'server.py', '--host', '127.0.0.1',
            '--port', str(config['listen_port']), '--enable_mirror', 'False', '--skip_install', 'True'],
            cwd=config['server_dir']))
    except KeyboardInterrupt:
        pass
