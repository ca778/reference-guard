from types import SimpleNamespace
import asyncio
import base64
import pymupdf
import pytest
from reference_guard.detector import detect
from reference_guard.selection import translation_ranges
from reference_guard.proxy import transform
from reference_guard.backend_adapter import FIELD
from reference_guard.layout import crop_pdf, two_columns
from tests.test_detector import pdf, BODY, REFS
from tests.test_proxy import CONFIG


def test_middle_references_preserve_appendix_and_stop_continuity():
    source = pdf([BODY, 'References\n' + REFS, REFS, 'Appendix A\n' + BODY, REFS])
    detection = detect(source)
    assert detection.reference_pages == [2, 3]
    assert detection.skip_last_pages == 0
    assert translation_ranges(5, detection.reference_pages) == '1,4-5'


@pytest.mark.parametrize('route', ['/translate', '/compare', '/crop-compare'])
def test_all_translation_routes_select_middle_pages(route):
    data = {'engine': 'pdf2zh_next', 'fileName': 'source.pdf',
            'fileContent': base64.b64encode(pdf([BODY, 'References\n' + REFS, 'Appendix A\n' + BODY])).decode()}
    result = asyncio.run(transform(data, {**CONFIG, 'page_selection_supported': True}, True, route=route))
    assert result[FIELD] == {'total': 3, 'excluded': [2]}
    assert result['onlyIncludeTranslatedPage'] is False


def test_crop_never_translates_and_client_cannot_forge_selection():
    data = {'engine': 'pdf2zh_next', FIELD: {'total': 3, 'excluded': [1, 3]}}
    result = asyncio.run(transform(data, CONFIG, True, route='/crop'))
    assert FIELD not in result


@pytest.mark.parametrize('excluded', [[0], [4], [True], [1, 2, 3], '2'])
def test_invalid_selection_rejected(excluded):
    with pytest.raises(ValueError):
        translation_ranges(3, excluded)


def test_single_column_crop_preserves_all_words(tmp_path):
    source = tmp_path / 'single.pdf'
    source.write_bytes(pdf([BODY, 'References\n' + REFS]))
    config = SimpleNamespace(pdf_w_offset=30, pdf_h_offset=90)
    for mode in ['origin-cut', 'crop-compare', 'dual-cut']:
        output = tmp_path / f'{mode}.pdf'
        crop_pdf(config, source, 'dual' if mode != 'origin-cut' else 'origin', output, mode)
        with pymupdf.open(source) as original, pymupdf.open(output) as result:
            assert not two_columns(original[0])
            assert len(result) == (1 if mode == 'crop-compare' else 2)
            words = ' '.join(p.get_text() for p in result).split()
            assert all(word in words for p in original for word in p.get_text().split())


def test_unpaired_dual_crop_does_not_lose_last_page(tmp_path):
    source = tmp_path / 'odd.pdf'; source.write_bytes(pdf([BODY]))
    with pytest.raises(ValueError, match='unpaired'):
        crop_pdf(SimpleNamespace(pdf_w_offset=0, pdf_h_offset=0), source, 'dual', tmp_path/'output.pdf', 'crop-compare')
