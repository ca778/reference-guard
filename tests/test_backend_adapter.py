from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local
from types import SimpleNamespace
import pytest
from reference_guard.backend_adapter import FIELD, install


def adapted_backend(barrier=None):
    request_state = local()
    namespace = {}

    class Translator:
        def process_request(self):
            return 'fixture.pdf', SimpleNamespace(skip_last_pages=0, engine='pdf2zh_next')

        def translate_pdf_next(self, path, config, task_id=None):
            if barrier:
                barrier.wait(timeout=5)
            return namespace['execute_with_progress'](['pdf2zh_next', path])

        def health_check(self):
            return SimpleNamespace(get_json=lambda: {'status': 'ok'}), 200

    namespace.update(PDFTranslator=Translator, Cropper=type('Cropper', (), {}),
                     execute_with_progress=lambda command: command,
                     request=SimpleNamespace(get_json=lambda **kwargs: request_state.data),
                     PdfReader=lambda path: SimpleNamespace(pages=[None] * 3),
                     args=SimpleNamespace(enable_winexe=False), jsonify=lambda data: data)
    install(namespace)
    return Translator(), namespace, request_state


def test_task_page_selection_isolated_between_threads_and_reset():
    translator, namespace, request_state = adapted_backend(Barrier(2))

    def run(excluded):
        request_state.data = {FIELD: {'total': 3, 'excluded': excluded}}
        path, config = translator.process_request()
        assert config.only_include_translated_page is False
        return translator.translate_pdf_next(path, config)

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(run, [2]); b = pool.submit(run, [3])
        assert a.result()[-2:] == ['--pages', '1,3']
        assert b.result()[-2:] == ['--pages', '1-2']
    assert namespace['execute_with_progress'](['unrelated']) == ['unrelated']


def test_backend_rejects_page_count_mismatch():
    translator, namespace, request_state = adapted_backend()
    request_state.data = {FIELD: {'total': 4, 'excluded': [2]}}
    with pytest.raises(ValueError, match='page count mismatch'):
        translator.process_request()
