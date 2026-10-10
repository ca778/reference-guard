"""Explicit real server check using the already translated one-page fixture/cache."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import tomllib
from pathlib import Path
from aiohttp import ClientSession, web
from launcher import port_free, stop_owned
from reference_guard.compatibility import ROOT, auto_allowed
from reference_guard.config import load_config
from reference_guard.proxy import create_app
from verify_outputs import verify


async def main():
    cfg=load_config()
    assert all(port_free(cfg[k]) for k in ['listen_port','backend_port']), 'Ports occupied: no existing process will be stopped'
    output=ROOT/'artifacts'/'http-verification'; output.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime('%Y%m%d-%H%M%S')
    backup=ROOT/'backups'/stamp; backup.mkdir(parents=True)
    config_dir=Path(cfg['server_dir'])/'config'
    before={p:p.read_bytes() for p in config_dir.glob('*') if p.is_file()}
    for p in before: shutil.copy2(p,backup/p.name)
    settings=tomllib.loads(before[config_dir/'config.toml'].decode('utf-8'))
    secrets=[str(v) for s in settings.values() if isinstance(s,dict) for k,v in s.items()
             if any(w in k.lower() for w in ['key','token','password']) and v]
    server=subprocess.Popen([cfg['server_python'],'server.py','--port',str(cfg['backend_port']),'--host','127.0.0.1',
        '--check_update','False','--enable_mirror','False','--skip_install','True'],cwd=cfg['server_dir'],
        env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUNBUFFERED':'1'},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    def log_reader():
        with (output/'server-sanitized.log').open('w',encoding='utf-8') as f:
            for raw in iter(server.stdout.readline,b''):
                line=raw.decode('utf-8',errors='replace')
                for secret in sorted(secrets,key=len,reverse=True):
                    line=line.replace(secret,'[REDACTED]')
                    if len(secret)>8: line=line.replace('********'+secret[-4:],'[REDACTED]')
                f.write(line); f.flush()
    reader=threading.Thread(target=log_reader,daemon=True); reader.start()
    runner=None; report={'timestamp':stamp,'auto_enabled':auto_allowed(cfg),'checks':{},'config_backup':str(backup)}
    try:
        async with ClientSession() as session:
            for attempt in range(120):
                if server.poll() is not None: raise RuntimeError('Official server startup failed')
                try:
                    async with session.get(f'http://127.0.0.1:{cfg["backend_port"]}/health') as res:
                        if res.status==200: break
                except Exception: pass
                await asyncio.sleep(.5)
            else: raise RuntimeError('Backend health timed out')
            runner=web.AppRunner(create_app(cfg)); await runner.setup()
            await web.TCPSite(runner,'127.0.0.1',cfg['listen_port']).start()
            base=f'http://127.0.0.1:{cfg["listen_port"]}'
            for route in ['/health','/api/tasks','/api/history','/api/config','/translatedInfo','/favicon.svg','/bo.mp3','/']:
                async with session.get(base+route) as prox, session.get(f'http://127.0.0.1:{cfg["backend_port"]}'+route) as direct:
                    pb,db=await prox.read(),await direct.read()
                    assert prox.status==direct.status and pb==db
                    report['checks'][route]='PASS'
            async with session.get(base+'/events') as res:
                assert res.status==200
                assert (await asyncio.wait_for(res.content.readuntil(b'\n\n'),5)).startswith(b'data:')
                report['checks']['sse']='PASS'
            original=ROOT/'artifacts'/'engine-verification'/'linked.pdf'
            payload={'fileName':f'reference-guard-http-{stamp}.pdf','fileContent':base64.b64encode(original.read_bytes()).decode(),
                     'engine':'pdf2zh_next','next_service':'deepseek','sourceLang':'en','targetLang':'zh-CN','asyncJob':True,
                     'skipLastPages':0,'onlyIncludeTranslatedPage':True,'dualMode':'LR','mono':True,'dual':True,
                     'noWatermark':True,'disableGlossary':True}
            # Field name is confirmed locally. No credential included in payload/log.
            payload['no_watermark']=True
            payload['disable_glossary']=True
            async with session.post(base+'/translate',json=payload) as res:
                accepted=await res.json(); assert res.status==200 and accepted['status']=='accepted'
            tid=accepted['taskId']; report['checks']['async_submit']='PASS'
            for _ in range(600):
                async with session.get(base+'/api/tasks') as res: tasks=(await res.json())['tasks']
                task=next((t for t in tasks if t['taskId']==tid),None)
                if task and task.get('finished'): break
                await asyncio.sleep(.5)
            else: raise RuntimeError('Real task did not finish')
            if task.get('error'): raise RuntimeError('Real task failed; inspect sanitized log')
            assert task['config']['skipLastPages']==1
            report['checks']['auto_skip']='PASS'; report['checks']['polling']='PASS'
            for name in task['fileList']:
                async with session.get(base+'/translatedFile/'+name) as res:
                    assert res.status==200
                    target=output/name; target.write_bytes(await res.read())
                if name.endswith('mono.pdf'): report['checks']['mono']=verify(original,target,'mono')
                if name.endswith('dual.pdf'): report['checks']['dual_lr']=verify(original,target,'dual_lr')
                async with session.get(base+'/translatedFile/'+name,headers={'Range':'bytes=0-3'}) as res:
                    assert res.status==206 and await res.read()==b'%PDF'
            report['checks']['download_and_range']='PASS'
            print('Actual official HTTP translation, auto skip, task polling, SSE, file download and Range: PASS',flush=True)
    finally:
        if runner: await runner.cleanup()
        stop_owned(server); reader.join(timeout=10)
        # Restore test-induced config writes byte-for-byte once the owned server has stopped.
        for p,content in before.items():
            if p.read_bytes()!=content: p.write_bytes(content)
        report['checks']['config_restored']='PASS' if all(p.read_bytes()==v for p,v in before.items()) else 'FAIL'
        report['checks']['ports_released']='PASS' if all(port_free(cfg[k]) for k in ['listen_port','backend_port']) else 'FAIL'
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__': asyncio.run(main())
