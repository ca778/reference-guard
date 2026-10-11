from __future__ import annotations
import argparse
import json
import os
import socket
import signal
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path
from reference_guard import __version__
from reference_guard.compatibility import ROOT, auto_allowed, fingerprint
from reference_guard.config import load_config


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def health(port: int) -> dict:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as r:
        d = json.load(r)
        if r.status != 200 or d.get('status') != 'ok':
            raise RuntimeError('Invalid health protocol')
        return d


def stop_owned(child: subprocess.Popen | None) -> None:
    if child is None or child.poll() is not None:
        return
    # Only our own recorded child PID; never look up or kill a process by occupied port.
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        child.terminate()
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill(); child.wait()


def main() -> int:
    if hasattr(signal, 'SIGBREAK'):
        def interrupted(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGBREAK, interrupted)
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-update', action='store_true', help='One-run test only; normal launch keeps official update checks')
    parser.add_argument('--passthrough', action='store_true', help='Disable automatic skipping for this launch')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--smoke-seconds', type=float, default=0, help='Bounded lifecycle check, no translation')
    args = parser.parse_args()
    cfg = load_config()
    if args.check:
        print(json.dumps({'fingerprint':fingerprint(cfg), 'auto':auto_allowed(cfg)},ensure_ascii=False,indent=2))
        return 0
    for p in (cfg['listen_port'],cfg['backend_port']):
        if not port_free(p):
            print(f'端口 {p} 已占用，请先关闭原启动窗口。不会结束占用进程。',flush=True)
            return 1
    env = {**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUNBUFFERED':'1'}
    if args.passthrough:
        env['REFERENCE_GUARD_PASSTHROUGH']='1'
    else:
        env.pop('REFERENCE_GUARD_PASSTHROUGH',None)
    print(f'[Reference Guard {__version__}] Ctrl+C 退出；官方更新检查：{not args.no_update}',flush=True)
    server = proxy = None
    try:
        for attempt in range(3):
            enabled, reason = auto_allowed(cfg)
            print(f'自动跳过：{enabled and not args.passthrough}；{reason}',flush=True)
            entry = [str(ROOT/'backend_entry.py'),str(Path(cfg['server_dir'])/'server.py')] if enabled and not args.passthrough else ['server.py']
            server = subprocess.Popen([cfg['server_python'],*entry,'--host','127.0.0.1','--port',str(cfg['backend_port']),
                '--enable_mirror','False','--skip_install','True','--check_update',str(not args.no_update)],
                cwd=cfg['server_dir'],env=env)
            deadline=time.monotonic()+300
            ready=False
            while time.monotonic()<deadline:
                if server.poll() is not None:
                    break
                try:
                    health(cfg['backend_port']); ready=True; break
                except Exception:
                    time.sleep(.5)
            if not ready:
                code=server.poll()
                stop_owned(server)
                if code==0 and attempt<2:
                    print('官方 Server 退出（可能完成更新）；重新检查后再启动。',flush=True)
                    continue
                raise RuntimeError('Backend failed startup/health, or retry limit reached')
            # Recheck after startup/update; no stale pre-update gate is trusted.
            proxy=subprocess.Popen([sys.executable,'-m','reference_guard.proxy'],cwd=ROOT,env=env)
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if proxy.poll() is not None:
                    raise RuntimeError('Proxy exited during startup')
                try:
                    health(cfg['listen_port']); break
                except Exception:
                    time.sleep(.25)
            else:
                raise RuntimeError('Proxy health timeout')
            print(f'就绪：Zotero 地址 http://127.0.0.1:{cfg["listen_port"]}；后端 {cfg["backend_port"]}',flush=True)
            smoke_deadline=time.monotonic()+args.smoke_seconds if args.smoke_seconds>0 else None
            while server.poll() is None and proxy.poll() is None:
                if smoke_deadline and time.monotonic()>=smoke_deadline:
                    print('PASS: 启动器健康检查与退出测试。',flush=True)
                    return 0
                time.sleep(.5)
            stop_owned(proxy); proxy=None
            stop_owned(server)
            if server.poll()==0 and attempt<2:
                print('后端正常退出；有限重启并重新兼容性检查。',flush=True)
                continue
            raise RuntimeError('Owned backend/proxy exited unexpectedly')
        return 1
    except KeyboardInterrupt:
        print('\n正在关闭本启动器创建的服务。',flush=True)
        return 0
    except Exception as exc:
        print(f'[ERROR] {exc}；可运行 restore-original.bat。',flush=True)
        return 1
    finally:
        stop_owned(proxy); stop_owned(server)

if __name__=='__main__':
    raise SystemExit(main())
