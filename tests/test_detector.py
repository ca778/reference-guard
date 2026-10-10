import pymupdf
import pytest
from reference_guard.detector import DEFAULT_HEADINGS, detect

BODY = 'We propose a method for reliable scientific document translation.\nOur results show that the method preserves the document content.'
REFS = '[1] Smith, J. Reliable document processing. Journal of Science, 2020.\n[2] Brown, A. Layout analysis. Proceedings of Computing, 2021.\n[3] Chen, B. PDF analysis. Journal of Systems, 2022. doi:10.1234/test'


def pdf(pages):
    with pymupdf.open() as d:
        for content in pages:
            p = d.new_page(width=600, height=800)
            if isinstance(content, str):
                p.insert_text((45, 65), content, fontsize=10)
            else:
                for x, y, text in content:
                    p.insert_text((x, y), text, fontsize=10)
        return d.tobytes()


@pytest.mark.parametrize('pages,count', [
    ([BODY, BODY], 0),
    ([BODY, 'References\n'+REFS, REFS, REFS], 3),
    ([BODY, [(45,65,BODY),(45,350,'References\n'+REFS)], REFS], 1),
    ([BODY, '7. REFERENCES\n'+REFS], 1),
    ([BODY, [(45,65,BODY),(325,65,'References\n'+REFS)], REFS], 1),
    ([BODY, 'References\n'+REFS, 'Appendix A\n'+BODY], 0),
    (['Contents\nReferences ........... 9', BODY], 0),
    ([BODY+'\nSee references for further discussion.', BODY], 0),
    ([BODY, '', 'References\n'+REFS], 1),
    ([BODY, 'References\n'+REFS, ''], 0),
    ([BODY, REFS], 0),
    ([BODY, 'References\n'+REFS, '[4] Doe, J. Short final reference. Journal, 2023.'], 2),
    ([BODY, 'References\n'+REFS, 'Author biographies\nProfessor Smith works at a university.'], 0),
    ([BODY, 'References\n'+REFS, 'Acknowledgements\nWe thank our collaborators.'], 0),
    ([BODY, 'Works Cited\n'+REFS], 1),
    ([BODY, 'Bibliography\n'+REFS], 1),
    ([BODY, 'Literature Cited\n'+REFS], 1),
    ([BODY, 'References\n'+REFS+'\nThis paper discusses References in titles.'], 0),
    ([BODY, 'A title containing References\n'+BODY], 0),
    ([BODY, 'References\n'+REFS+'\nDr. Smith is a professor of computer science.'], 0),
    ([BODY, [(45,65,'References\n'+REFS),(45,240,'Further explanatory notes are provided below.')]], 0),
])
def test_suffix(pages, count):
    result = detect(pdf(pages))
    assert result.skip_last_pages == count
    assert result.last_translatable_page == len(pages)-count
    assert result.total_pages == len(pages)


def test_mixed_classification():
    r = detect(pdf([BODY, [(45,65,BODY),(45,350,'References\n'+REFS)], REFS]))
    assert r.pages[1].classification == 'MIXED'
    assert r.references_heading_page == r.references_start_page == 2
    assert r.last_translatable_page == 2


def test_scanned():
    with pymupdf.open() as d:
        p = d.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0,0,100,100), False)
        pix.clear_with(220)
        p.insert_image(p.rect, pixmap=pix)
        assert detect(d.tobytes()).pages[0].classification == 'UNKNOWN'


def test_invalid():
    with pytest.raises(Exception):
        detect(b'not pdf')


def test_chinese_heading():
    with pymupdf.open(stream=pdf([BODY,'']),filetype='pdf') as d:
        d[1].insert_text((45,65),'参考文献',fontname='china-s',fontsize=12)
        d[1].insert_text((45,95),REFS,fontsize=10)
        assert detect(d.tobytes()).skip_last_pages==1


def test_small_footnote_heading_not_accepted():
    with pymupdf.open(stream=pdf([BODY,'']),filetype='pdf') as d:
        d[1].insert_text((45,65),'References',fontsize=6)
        d[1].insert_text((45,95),REFS,fontsize=10)
        assert detect(d.tobytes()).skip_last_pages==0


def test_footer_and_folio_ignored():
    with pymupdf.open(stream=pdf([BODY,'References\n'+REFS]),filetype='pdf') as d:
        d[1].insert_text((280,780),'2',fontsize=8)
        d[1].insert_text((45,25),'References',fontsize=8)
        assert detect(d.tobytes()).skip_last_pages==1


def test_running_title_and_url_fragment():
    with pymupdf.open(stream=pdf([BODY,'References\n'+REFS,REFS]),filetype='pdf') as d:
        for p in d:
            p.insert_text((240,45),'Research Paper',fontsize=8)
        d[2].insert_text((45,240),'3e9f0fc9b2f89e043bc6233994dfcf76-\nAbstract.html.',fontsize=10)
        assert detect(d.tobytes()).skip_last_pages==2


def test_short_body_at_top_is_preserved():
    with pymupdf.open(stream=pdf([BODY,'References\n'+REFS]),filetype='pdf') as d:
        d[1].insert_text((45,25),'We show a new theorem.',fontsize=10)
        assert detect(d.tobytes()).skip_last_pages==0


@pytest.mark.parametrize('title', DEFAULT_HEADINGS)
def test_all_builtin_titles(title):
    with pymupdf.open(stream=pdf([BODY,'']),filetype='pdf') as d:
        font='china-s' if any('\u4e00'<=c<='\u9fff' for c in title) else 'helv'
        d[1].insert_text((45,65),title,fontname=font,fontsize=12)
        d[1].insert_text((45,95),REFS,fontsize=10)
        assert detect(d.tobytes()).skip_last_pages==1


@pytest.mark.parametrize('title', ['12.  REFERENCE LIST :', 'IV. Bibliographic References.', 'Selected Literature'])
def test_numbered_and_custom_titles(title):
    r=detect(pdf([BODY,title+'\n'+REFS]),extra_headings=['Selected Literature'])
    assert r.skip_last_pages==1


@pytest.mark.parametrize('title', ['Notes', 'Endnotes', 'Sources', 'References and Notes', 'Notes and References'])
def test_ambiguous_titles_fall_back(title):
    assert detect(pdf([BODY,title+'\n'+REFS])).skip_last_pages==0


def test_custom_alias_is_literal_not_regex():
    assert detect(pdf([BODY,'Research (Sources)\n'+REFS]),extra_headings=['Research (Sources)']).skip_last_pages==1
    assert detect(pdf([BODY,'Research Sources\n'+REFS]),extra_headings=['Research (Sources)']).skip_last_pages==0


def test_alias_title_in_body_not_heading():
    assert detect(pdf([BODY+'\nSee the Reference List for additional sources.',BODY])).skip_last_pages==0


def test_custom_heading_does_not_skip_appendix():
    assert detect(pdf([BODY,'Selected Literature\n'+REFS,'Appendix A\n'+BODY]),extra_headings=['Selected Literature']).skip_last_pages==0
