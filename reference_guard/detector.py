"""Conservative, layout-aware reference suffix detection. Public pages are 1-based."""
from __future__ import annotations

import re
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

import pymupdf

DEFAULT_HEADINGS = (
    'References', 'Reference', 'Bibliography', 'Works Cited', 'Literature Cited',
    'Reference List', 'List of References', 'Cited References', 'References Cited',
    'Literature References', 'Cited Literature', 'Bibliographic References',
    'Bibliography and References', 'References and Bibliography',
    '参考文献', '引用文献', '文献目录',
)


def heading_pattern(extra_titles: Sequence[str] = ()) -> re.Pattern[str]:
    """Exact literal aliases only; user configuration never becomes arbitrary regex."""
    if isinstance(extra_titles, str) or len(extra_titles) > 64:
        raise ValueError('reference_heading_aliases must be a list of at most 64 titles')
    if any(not isinstance(t, str) or not t.strip() or len(t) > 120 or '\n' in t or '\r' in t for t in extra_titles):
        raise ValueError('Invalid literal reference heading alias')
    alternatives = []
    for title in (*DEFAULT_HEADINGS, *extra_titles):
        alternatives.append(r'\s+'.join(re.escape(word) for word in title.split()))
    return re.compile(r'^(?:(?:\d+(?:\.\d+)*|[IVX]+)[.)]?\s+)?(?:' + '|'.join(alternatives) + r')\s*[.:：]?\s*$', re.I)


HEADING = heading_pattern()
OTHER = re.compile(r'^(?:(?:[A-Z]|\d+(?:\.\d+)*)[.)]?\s+)?(?:appendix|appendices|acknowledg(?:e)?ments?|supplement(?:ary)?(?: material)?|author biographies|biograph(?:y|ies)|about the authors|conclusion|discussion|附录|致谢)\b', re.I)
YEAR = re.compile(r'\b(?:19|20)\d{2}[a-z]?\b')
ENTRY = re.compile(r'^\s*(?:\[\d{1,4}\]|\d{1,4}[.)]\s|[A-ZÀ-Ž][\wÀ-ž\-\u0027]+,\s)')
BODY = re.compile(r'\b(?:we (?:show|propose|evaluate|find|use)|our (?:method|results|model)|in conclusion|this (?:paper|study|section)|as shown in|experimental results)\b', re.I)
NONREFERENCE = re.compile(r'^(?:Dr\.\s|Professor\s|The authors?\s|Correspondence\b|Funding\b|Data availability\b|Code availability\b|Conflict(?:s)? of interest\b|Supplementary (?:notes?|information)\b)', re.I)


@dataclass
class PageEvidence:
    page: int
    classification: str
    reference_entries: int = 0
    year_count: int = 0
    reason: str = ''


@dataclass
class Detection:
    total_pages: int
    references_heading_page: int | None = None
    references_start_page: int | None = None
    last_translatable_page: int = 0
    skip_last_pages: int = 0
    confidence: str = 'LOW'
    reason: str = ''
    detection_status: str = 'FALLBACK'
    pages: list[PageEvidence] = field(default_factory=list)
    reference_pages: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def detect(pdf: bytes, max_pages: int = 2000, extra_headings: Sequence[str] = ()) -> Detection:
    heading = heading_pattern(extra_headings)
    with pymupdf.open(stream=pdf, filetype='pdf') as doc:
        if doc.is_encrypted or not 0 < len(doc) <= max_pages:
            raise ValueError('Encrypted PDF or page limit exceeded')
        result = Detection(len(doc), last_translatable_page=len(doc))
        running_counts: dict[str, int] = {}
        for page in doc:
            page_heads = set()
            for b in page.get_text('blocks'):
                t=b[4].strip()
                if b[6]==0 and len(t)<120 and b[3]<page.rect.height*.10:
                    page_heads.add(t)
            for t in page_heads:
                running_counts[t]=running_counts.get(t,0)+1
        running_heads={t for t,count in running_counts.items() if count>=3 and not heading.fullmatch(t)}
        active = False
        obstructed = False
        for index, page in enumerate(doc):
            # Retain lines, font sizes, and column geometry; no full-text substring heading matching.
            lines = []
            for block in page.get_text('dict')['blocks']:
                if block['type'] != 0:
                    continue
                for line in block['lines']:
                    text = ''.join(s['text'] for s in line['spans']).strip()
                    x0, y0, x1, y1 = line['bbox']
                    # Ignore identified recurring heads and marginal folios, never arbitrary prose.
                    folio = text.isdigit() and len(text) <= 4 and (y1 < page.rect.height * .10 or y0 > page.rect.height * .90)
                    running = text in running_heads and y1 < page.rect.height*.10
                    if not text or running or folio:
                        continue
                    lines.append((text, x0, y0, x1, y1, max(s['size'] for s in line['spans'])))
            ev = PageEvidence(index + 1, 'BODY')
            result.pages.append(ev)
            if not lines:
                ev.classification, ev.reason = 'UNKNOWN', 'No reliable text; scan or blank page'
                if active:
                    obstructed = True
                    active = False
                continue
            headings = [l for l in lines if heading.fullmatch(l[0])]
            # A real heading needs bibliographic evidence below it, in the same column.
            accepted = None
            for h in headings:
                if h[5] < statistics.median(l[5] for l in lines) * .95:
                    continue  # Small footnote text is not a section heading.
                below = [l for l in lines if l[2] > h[2] and abs(l[1] - h[1]) < page.rect.width * .18]
                text = '\n'.join(l[0] for l in below)
                if YEAR.search(text) and (any(ENTRY.match(l[0]) for l in below) or len(YEAR.findall(text)) >= 2):
                    accepted = h
                    break
            if accepted:
                active = True
                if result.references_heading_page is None:
                    result.references_heading_page = index + 1
                    result.references_start_page = index + 1
            if not active:
                ev.reason = 'No substantiated reference heading'
                continue
            content = [l for l in lines if l not in headings]
            texts = [l[0] for l in content]
            ev.reference_entries = sum(bool(ENTRY.match(t)) for t in texts)
            ev.year_count = len(YEAR.findall('\n'.join(texts)))
            # Any later non-reference section disables the entire automatic suffix operation.
            later = content if not accepted else [l for l in content if
                (l[1] > accepted[1] + page.rect.width * .20) or
                (abs(l[1]-accepted[1]) < page.rect.width * .20 and l[2] > accepted[2])]
            if any(OTHER.match(l[0]) or NONREFERENCE.match(l[0]) for l in later):
                obstructed = True
                active = False
                ev.reason = 'Non-reference section after reference heading'
                continue
            before = []
            if accepted:
                before = [l for l in content if l[2] < accepted[2] - 2 or
                          (l[1] < accepted[1] - page.rect.width * .20)]
            text = '\n'.join(texts)
            # Reference-list density plus no explicit body phrases. One final entry is allowed
            # only following an already-established list and with an entry marker + year.
            strong = ev.year_count >= 2 and (ev.reference_entries >= 2 or ev.year_count >= 3)
            short_final = index == len(doc)-1 and ev.reference_entries >= 1 and ev.year_count >= 1 and len(text) < 1100
            # Unanchored paragraphs are ambiguous, even when a year happens to occur.
            blocks = page.get_text('blocks')
            suspicious = []
            for b in blocks:
                if b[6] != 0:
                    continue
                t = b[4].strip()
                running = t in running_heads and b[3] < page.rect.height*.10
                if running or (len(t) <= 4 and t.isdigit()):
                    continue
                if heading.fullmatch(t):
                    continue
                url_fragment=bool(re.match(r'^[a-f0-9]{16,}',t)) and bool(re.search(r'\.(?:html|pdf)\b',t,re.I))
                if not (YEAR.search(t) or ENTRY.match(t) or re.search(r'\b(?:doi|arxiv)\b', t, re.I) or url_fragment):
                    suspicious.append(t)
            if before or BODY.search(text):
                ev.classification, ev.reason = 'MIXED', 'Body content above/beside heading or explicit body prose'
                if not accepted:
                    active = False
            elif (strong or short_final) and not suspicious:
                ev.classification, ev.reason = 'REFERENCES_ONLY', 'Heading continuity, bibliographic density, no unexplained prose'
                result.reference_pages.append(index + 1)
            else:
                ev.classification, ev.reason = 'UNKNOWN', 'Insufficient bibliographic evidence or unexplained prose'
                obstructed = True
                active = False
        if obstructed:
            result.reason = 'Ambiguous text/scan/other section after References: preserve original behavior'
            return result
        suffix = 0
        for ev in reversed(result.pages):
            if ev.classification != 'REFERENCES_ONLY':
                break
            suffix += 1
        if 0 < suffix < result.total_pages:
            result.skip_last_pages = suffix
            result.last_translatable_page = result.total_pages - suffix
            result.confidence = 'HIGH'
            result.detection_status = 'DETECTED'
            result.reason = 'Substantiated heading + continuous bibliographic tail + no ambiguous/later section'
        else:
            result.reason = 'No safe reference suffix, or would skip entire PDF'
        return result
