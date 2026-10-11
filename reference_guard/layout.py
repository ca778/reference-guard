"""Conservative column-aware cropping: never bisect single-column text lines."""
from __future__ import annotations
import pymupdf


def two_columns(page) -> bool:
    middle = page.rect.width / 2
    lines = [pymupdf.Rect(line['bbox']) for block in page.get_text('dict')['blocks']
             if block['type'] == 0 for line in block['lines']
             if sum(len(span['text'].strip()) for span in line['spans']) >= 12]
    crossing = sum(r.x0 < middle - 8 and r.x1 > middle + 8 for r in lines)
    left = sum(r.x1 <= middle + 8 for r in lines)
    right = sum(r.x0 >= middle - 8 for r in lines)
    return len(lines) >= 12 and crossing == 0 and left >= 5 and right >= 5


def safe_clip(page, config):
    rect = page.rect
    dx = max(0, min(float(config.pdf_w_offset), rect.width * .2))
    dy = max(0, min(float(config.pdf_h_offset), rect.height * .2))
    clip = pymupdf.Rect(rect.x0 + dx, rect.y0 + dy, rect.x1 - dx, rect.y1 - dy)
    # Requested margin trims may not remove text. Expand to include all glyphs.
    for word in page.get_text('words'):
        clip |= pymupdf.Rect(word[:4])
    return clip & rect


def crop_pdf(config, input_pdf, infile_type, output_pdf, outfile_type):
    dual = outfile_type in {'dual-cut', 'crop-compare'}
    with pymupdf.open(input_pdf) as source, pymupdf.open() as out:
        if dual and len(source) % 2:
            raise ValueError('Reference Guard: unpaired dual page; refusing to lose the final page')
        for index in range(0, len(source), 2 if dual else 1):
            pages = [source[index], source[index + 1]] if dual else [source[index]]
            split = all(two_columns(page) for page in pages)
            clips = [safe_clip(page, config) for page in pages]
            for column in range(2 if split else 1):
                selected = []
                for page, clip in zip(pages, clips):
                    if split:
                        midpoint = page.rect.width / 2
                        clip = pymupdf.Rect(clip.x0 if column == 0 else midpoint, clip.y0,
                                            midpoint if column == 0 else clip.x1, clip.y1)
                    selected.append(clip)
                if outfile_type == 'crop-compare':
                    height = max(c.height for c in selected)
                    target = out.new_page(width=sum(c.width for c in selected), height=height)
                    x = 0
                    for page, clip in zip(pages, selected):
                        target.show_pdf_page(pymupdf.Rect(x, 0, x + clip.width, clip.height), source, page.number, clip=clip)
                        x += clip.width
                else:
                    for page, clip in zip(pages, selected):
                        target = out.new_page(width=clip.width, height=clip.height)
                        target.show_pdf_page(target.rect, source, page.number, clip=clip)
        if not len(out):
            raise ValueError('Empty crop input')
        out.save(output_pdf, garbage=4, deflate=True)
