"""In-memory adapter; official files, updates and request lifecycle stay upstream."""
from __future__ import annotations
from contextvars import ContextVar
from .selection import translation_ranges
from .layout import crop_pdf

CAPABILITY = 'reference-guard-page-selection-v1'
FIELD = '_referenceGuardSelection'


def install(namespace: dict) -> None:
    translator = namespace['PDFTranslator']
    process = translator.process_request
    translate = translator.translate_pdf_next
    execute = namespace['execute_with_progress']
    health = translator.health_check
    selection = ContextVar('reference_guard_selection', default=None)

    def process_request(self):
        path, config = process(self)
        data = namespace['request'].get_json(silent=True) or {}
        plan = data.get(FIELD)
        if plan and not config.skip_last_pages and config.engine == 'pdf2zh_next':
            total = len(namespace['PdfReader'](path).pages)
            if not isinstance(plan, dict) or plan.get('total') != total:
                raise ValueError('Reference Guard: page count mismatch')
            config.reference_guard_pages = translation_ranges(total, plan.get('excluded'))
            config.only_include_translated_page = False
        return path, config

    def translate_pdf_next(self, path, config, task_id=None):
        if getattr(config, 'reference_guard_pages', None) and namespace['args'].enable_winexe:
            raise ValueError('Reference Guard: executable mode page selection is not verified; use the Python engine')
        token = selection.set(getattr(config, 'reference_guard_pages', None))
        try:
            return translate(self, path, config, task_id)
        finally:
            selection.reset(token)

    def execute_with_progress(command, *args, **kwargs):
        pages = selection.get()
        if pages:
            command = list(command)
            if '--pages' in command:
                index = command.index('--pages')
                del command[index:index + 2]
            command.extend(['--pages', pages])
            print(f'[Reference Guard] Actual engine translation pages: {pages}', flush=True)
        return execute(command, *args, **kwargs)

    def health_check(self):
        response, status = health(self)
        payload = response.get_json()
        payload['referenceGuardCapability'] = CAPABILITY
        return namespace['jsonify'](payload), status

    translator.process_request = process_request
    translator.translate_pdf_next = translate_pdf_next
    translator.health_check = health_check
    namespace['execute_with_progress'] = execute_with_progress
    namespace['Cropper'].crop_pdf = staticmethod(crop_pdf)
