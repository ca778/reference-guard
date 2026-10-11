from __future__ import annotations
import asyncio
import base64
import json
import logging
import os
import sys
import tomllib
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web
from multidict import CIMultiDict
from yarl import URL

from .compatibility import ROOT, auto_allowed
from .config import load_config
from .backend_adapter import CAPABILITY, FIELD
from .selection import translation_ranges

LOG = logging.getLogger('reference_guard')
SESSION = web.AppKey('session', ClientSession)
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'}
PROCESSING = {'/translate', '/crop', '/compare', '/crop-compare'}


class UploadTooLarge(Exception):
    pass


def headers_without_hop(headers, modified: bool = False) -> CIMultiDict:
    excluded = HOP | {v.strip().lower() for v in headers.get('Connection', '').split(',')}
    excluded |= {'host'}
    if modified:
        excluded |= {'content-length', 'content-encoding', 'content-md5', 'digest'}
    return CIMultiDict((k, v) for k, v in headers.items() if k.lower() not in excluded)


async def run_detection(pdf: bytes, config: dict) -> dict:
    process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'reference_guard.worker',
        cwd=ROOT, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(process.communicate(json.dumps({'pdf': base64.b64encode(pdf).decode(),
            'max_pages': config['max_detector_pages'],
            'extra_headings': config.get('reference_heading_aliases', [])}).encode()), config['detection_timeout_seconds'])
        return json.loads(out)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def transform(data: dict, config: dict, enabled: bool, detector=run_detection, route='/translate') -> dict:
    if FIELD in data:
        data = {k: v for k, v in data.items() if k != FIELD}
    if route == '/crop':
        LOG.info('Mode: CROP_ONLY; upstream cropping does not translate any pages')
        return data
    name = str(data.get('fileName', ''))
    if route != '/translate' and any(s in name for s in ('.dual.pdf', '_dual.pdf', '.dual-cut.pdf', '-dual.pdf', '-dual-cut.pdf')):
        LOG.info('Mode: EXISTING_DUAL; formatting only; existing translations cannot be undone')
        return data
    try:
        manual = int(data.get('skipLastPages', 0)) > 0
    except (TypeError, ValueError):
        manual = False
    if manual:
        LOG.info('Mode: MANUAL; skipLastPages retained; onlyIncludeTranslatedPage retained: %s',
                 str(data.get('onlyIncludeTranslatedPage', False)).strip().lower() in {'true','1','yes'})
        return data
    if not enabled or not config.get('auto_skip_references') or data.get('engine') != 'pdf2zh_next':
        return data
    try:
        content = data.get('fileContent')
        if not isinstance(content, str):
            return data
        prefix = 'data:application/pdf;base64,'
        content = content[len(prefix):] if content.startswith(prefix) else content
        if len(content) > config['max_pdf_mb'] * 1024 * 1024 * 4 // 3 + 4:
            LOG.warning('Detection size limit: original request forwarded')
            return data
        pdf = base64.b64decode(content, validate=True)
        result = await detector(pdf, config)
        excluded = result.get('reference_pages', [])
        if excluded and config.get('page_selection_supported'):
            pages = translation_ranges(result['total_pages'], excluded)
            LOG.info('Route: %s; Mode: AUTO_PAGES; Reference pages: %s; Translation pages: %s', route, excluded, pages)
            return {**data, 'skipLastPages': 0, 'onlyIncludeTranslatedPage': False,
                    FIELD: {'total': result['total_pages'], 'excluded': excluded}}
        count = result.get('skip_last_pages', 0)
        if count:
            LOG.info('Pure reference suffix: pages %s-%s', result['last_translatable_page'] + 1, result['total_pages'])
        LOG.info('PDF pages: %s; References heading: page %s; Reference start: page %s; Last translatable page: %s; SkipLastPages: %s; Mode: %s; Confidence: %s; Reason: %s',
                 result.get('total_pages'), result.get('references_heading_page'), result.get('references_start_page'),
                 result.get('last_translatable_page'), count, 'AUTO' if count else 'FALLBACK', result.get('confidence'), result.get('reason'))
        if result.get('confidence') == 'HIGH' and result.get('detection_status') == 'DETECTED' and 0 < count < result['total_pages']:
            return {**data, 'skipLastPages': count, 'onlyIncludeTranslatedPage': False}
    except Exception:
        # No exception text: third party parsers may include PDF text or request secrets.
        LOG.warning('Detector failed; original request forwarded')
    return data


async def wait_backend_idle(session: ClientSession, backend: str, timeout: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        async with session.get(backend + '/api/tasks') as response:
            payload = await response.json()
            tasks = payload.get('tasks') if isinstance(payload, dict) else None
            if response.status != 200 or not isinstance(tasks, list):
                raise RuntimeError('Task protocol incompatible')
            if not any(t.get('active') is not False for t in tasks):
                return
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError('Previous task has not finished')
        await asyncio.sleep(.25)


def create_app(config: dict, enabled: bool | None = None) -> web.Application:
    if not (1 <= config['backend_port'] <= 65535 and 1 <= config['listen_port'] <= 65535) or config['backend_port'] == config['listen_port']:
        raise ValueError('Invalid fixed loopback ports')
    if enabled is None:
        enabled, reason = auto_allowed(config)
        LOG.warning('Automatic reference skip: %s; %s', enabled, reason)
    if os.environ.get('REFERENCE_GUARD_PASSTHROUGH') == '1':
        enabled = False
    backend = f"http://127.0.0.1:{config['backend_port']}"
    app = web.Application(client_max_size=config['max_request_mb'] * 1024 * 1024)
    detector_slots = asyncio.Semaphore(config['max_parallel_detections'])
    submit_lock = asyncio.Lock()

    async def session_context(app):
        async with ClientSession(auto_decompress=False, timeout=ClientTimeout(total=None,
            sock_connect=config['backend_connect_timeout_seconds'], sock_read=config['backend_read_timeout_seconds'])) as session:
            app[SESSION] = session
            yield
    app.cleanup_ctx.append(session_context)

    async def forward(request):
        session = app[SESSION]
        # raw_path preserves percent encoding and query order; target cannot be user-selected.
        target = URL(backend + request.raw_path, encoded=True)
        async def bounded_upload():
            size=0
            async for chunk in request.content.iter_chunked(65536):
                size+=len(chunk)
                if size>config['max_request_mb'] * 1024 * 1024:
                    raise UploadTooLarge()
                yield chunk
        data = bounded_upload()
        modified = False
        if request.method == 'POST' and request.path in PROCESSING:
            raw = await request.read()
            data = raw
            if request.content_type == 'application/json' and not request.headers.get('Content-Encoding'):
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict):
                        async with detector_slots:
                            async with session.get(backend + '/health') as health_response:
                                capability = (await health_response.json()).get('referenceGuardCapability') if health_response.status == 200 else None
                            runtime_config = {**config, 'page_selection_supported': capability == CAPABILITY}
                            changed = await transform(obj, runtime_config, enabled, route=request.path)
                        if changed is not obj:
                            data = json.dumps(changed, ensure_ascii=False).encode()
                            modified = True
                except (ValueError, UnicodeError):
                    LOG.warning('Malformed JSON forwarded to official Server')
        upstream = await session.request(request.method, target, data=data,
            headers=headers_without_hop(request.headers, modified), allow_redirects=False)
        try:
            response = web.StreamResponse(status=upstream.status, reason=upstream.reason,
                                          headers=headers_without_hop(upstream.headers))
            await response.prepare(request)
            request['response_started'] = True
            if request.method != 'HEAD':
                async for chunk in upstream.content.iter_chunked(65536):
                    await response.write(chunk)
            await response.write_eof()
            return response
        except ConnectionResetError:
            if request.transport is None or request.transport.is_closing():
                return response  # Normal SSE/download client disconnect.
            raise
        finally:
            upstream.close()

    async def handler(request):
        try:
            if request.content_length and request.content_length > config['max_request_mb'] * 1024 * 1024:
                raise web.HTTPRequestEntityTooLarge(max_size=config['max_request_mb']*1024*1024,actual_size=request.content_length)
            if request.method == 'POST' and request.path in PROCESSING:
                # Shared upstream config and filenames are protected through task completion.
                async with submit_lock:
                    await wait_backend_idle(app[SESSION], backend, config['backend_read_timeout_seconds'])
                    return await forward(request)
            return await forward(request)
        except web.HTTPException:
            raise
        except (ConnectionResetError, asyncio.CancelledError):
            raise
        except Exception as exc:
            cause = exc
            while cause is not None:
                if isinstance(cause, UploadTooLarge):
                    raise web.HTTPRequestEntityTooLarge(max_size=config['max_request_mb']*1024*1024,actual_size=config['max_request_mb']*1024*1024+1)
                cause=cause.__cause__
            LOG.error('Backend transport/protocol failure')
            if request.get('response_started'):
                if request.transport:
                    request.transport.close()
                raise
            return web.json_response({'status': 'error', 'message': 'Reference Guard: backend unavailable, timeout or incompatible task protocol'}, status=502)
    app.router.add_route('*', '/{path:.*}', handler)
    return app


def main():
    config = load_config()
    (ROOT / 'logs').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='[Reference Guard] %(asctime)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(ROOT / 'logs' / 'guard.log', encoding='utf-8')])
    web.run_app(create_app(config), host='127.0.0.1', port=config['listen_port'], access_log=None)

if __name__ == '__main__':
    main()
