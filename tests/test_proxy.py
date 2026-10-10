import asyncio
import base64
import json
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp import ClientSession, web
from yarl import URL
from reference_guard.proxy import create_app, transform, headers_without_hop
from tests.test_detector import pdf, BODY, REFS
from reference_guard.config import load_config

CONFIG = load_config()


def request_pdf():
    return {'fileContent':base64.b64encode(pdf([BODY,'References\n'+REFS])).decode(),
            'fileName':'fixture.pdf','engine':'pdf2zh_next','onlyIncludeTranslatedPage':True,
            'authorization':'sensitive-test-value','asyncJob':True}


def test_transform_and_manual(caplog):
    async def scenario():
        data = request_pdf()
        out = await transform(data, CONFIG, True)
        assert out['skipLastPages']==1 and out['onlyIncludeTranslatedPage'] is False
        assert data['onlyIncludeTranslatedPage'] is True and 'skipLastPages' not in data
        assert out['authorization'] == data['authorization']
        data['skipLastPages']='2'
        assert await transform(data, CONFIG, True) is data
        assert 'sensitive-test-value' not in caplog.text
    asyncio.run(scenario())


@pytest.mark.parametrize('content', ['bad base64', base64.b64encode(b'bad PDF').decode()])
def test_bad_pdf(content):
    data = request_pdf(); data['fileContent']=content
    assert asyncio.run(transform(data, CONFIG, True)) is data


def test_detector_exception():
    async def broken(*args): raise RuntimeError('secret')
    data=request_pdf()
    assert asyncio.run(transform(data,CONFIG,True,broken)) is data


def test_disabled():
    data=request_pdf()
    assert asyncio.run(transform(data,CONFIG,False)) is data


def test_custom_alias_reaches_isolated_worker():
    data=request_pdf()
    data['fileContent']=base64.b64encode(pdf([BODY,'Selected Literature\n'+REFS])).decode()
    cfg={**CONFIG,'reference_heading_aliases':['Selected Literature']}
    out=asyncio.run(transform(data,cfg,True))
    assert out['skipLastPages']==1 and out['onlyIncludeTranslatedPage'] is False


def test_invalid_alias_configuration_falls_back():
    data=request_pdf()
    assert asyncio.run(transform(data,{**CONFIG,'reference_heading_aliases':'bad list'},True)) is data


def test_hop_headers():
    assert 'Authorization' in headers_without_hop({'Authorization':'x','Connection':'x-test','X-Test':'y'})
    assert 'X-Test' not in headers_without_hop({'Connection':'x-test','X-Test':'y'})


def test_streaming_protocol_and_concurrency():
    async def scenario():
        tasks=[]; received=[]; overlaps=[]
        async def backend(req):
            if req.path=='/api/tasks':
                return web.json_response({'tasks':tasks,'status':'success'})
            if req.path=='/translate':
                overlaps.append(sum(t['active'] for t in tasks))
                body=await req.json(); received.append(body)
                tid=str(len(received)); t={'taskId':tid,'active':True,'finished':False}; tasks.append(t)
                async def finish():
                    await asyncio.sleep(.2); t.update(active=False,finished=True)
                if body.get('asyncJob') is False:
                    await finish()
                    return web.json_response({'status':'success','fileList':['fixture.mono.pdf'],'filePaths':['mock-output/fixture.mono.pdf'],'outputDir':'mock-output'})
                asyncio.create_task(finish())
                return web.json_response({'status':'accepted','taskId':tid})
            if req.path=='/events':
                response=web.StreamResponse(headers={'Content-Type':'text/event-stream'})
                await response.prepare(req)
                await response.write(b'data: first\n\n')
                await asyncio.sleep(.3)
                await response.write(b'data: second\n\n'); return response
            if req.path.startswith('/translatedFile/'):
                assert req.headers.get('Range')=='bytes=0-3'
                return web.Response(body=b'%PDF',status=206,headers={'Content-Range':'bytes 0-3/100','Content-Disposition':'attachment; filename="test.pdf"'})
            return web.json_response({'raw_path':req.raw_path,'method':req.method,'body':(await req.read()).decode()}, status=201,headers={'X-Original':'yes'})
        upstream=web.Application(); upstream.router.add_route('*','/{path:.*}',backend)
        ur=web.AppRunner(upstream); await ur.setup(); us=web.TCPSite(ur,'127.0.0.1',0); await us.start()
        cfg={**CONFIG,'backend_port':us._server.sockets[0].getsockname()[1]}
        pr=web.AppRunner(create_app(cfg,True)); await pr.setup(); ps=web.TCPSite(pr,'127.0.0.1',0); await ps.start()
        base='http://127.0.0.1:'+str(ps._server.sockets[0].getsockname()[1])
        try:
            async with ClientSession() as client:
                async def submit():
                    async with client.post(base+'/translate',json=request_pdf()) as res:
                        assert res.status==200
                        return await res.json()
                a,b=await asyncio.gather(submit(),submit())
                assert a['taskId'] != b['taskId'] and overlaps==[0,0]
                assert all(r['skipLastPages']==1 and r['onlyIncludeTranslatedPage'] is False for r in received)
                async with client.get(base+'/api/tasks') as res: assert 'tasks' in await res.json()
                legacy=request_pdf(); legacy['asyncJob']=False
                async with client.post(base+'/translate',json=legacy) as res:
                    assert (await res.json())=={'status':'success','fileList':['fixture.mono.pdf'],'filePaths':['mock-output/fixture.mono.pdf'],'outputDir':'mock-output'}
                for route in ['/crop','/compare','/crop-compare']:
                    raw=json.dumps(request_pdf()).encode()
                    async with client.post(base+route,data=raw,headers={'Content-Type':'application/json'}) as res:
                        assert res.status==201 and (await res.json())['body'].encode()==raw
                async with client.get(base+'/events') as res:
                    first=await asyncio.wait_for(res.content.readuntil(b'\n\n'),.2)
                    assert first==b'data: first\n\n'
                    assert b'second' in await res.read()
                async with client.get(base+'/translatedFile/a%20b.pdf',headers={'Range':'bytes=0-3'}) as res:
                    assert res.status==206 and await res.read()==b'%PDF' and 'Content-Disposition' in res.headers
                async with client.head(base+'/translatedFile/a%20b.pdf',headers={'Range':'bytes=0-3'}) as res:
                    assert res.status==206 and await res.read()==b'' and res.headers['Content-Length']=='4'
                async with client.patch(URL(base+'/unknown%20path?x=a%2Fb&x=2', encoded=True),data='payload') as res:
                    assert res.status==201 and res.headers['X-Original']=='yes'
                    assert (await res.json())=={'raw_path':'/unknown%20path?x=a%2Fb&x=2','method':'PATCH','body':'payload'}
                async with client.post(base+'/translate',data=b'{bad',headers={'Content-Type':'application/json'}) as res:
                    assert res.status==500  # fake backend rejects unchanged malformed JSON
                cfg['max_request_mb']=.00001
                async with client.post(base+'/translate',data=b'x'*100) as res:
                    assert res.status==413
                await ur.cleanup()
                async with client.get(base+'/health') as res:
                    assert res.status==502 and (await res.json())['status']=='error'
        finally:
            await pr.cleanup(); await ur.cleanup()
    asyncio.run(scenario())
