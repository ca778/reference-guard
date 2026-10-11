"""Page selection without removing source or output pages."""
from __future__ import annotations


def translation_ranges(total: int, excluded: list[int]) -> str:
    if type(total) is not int or total < 1 or not isinstance(excluded, list):
        raise ValueError('Invalid page selection')
    if any(type(p) is not int or not 1 <= p <= total for p in excluded):
        raise ValueError('Invalid excluded page')
    keep = [p for p in range(1, total + 1) if p not in set(excluded)]
    if not keep:
        raise ValueError('Cannot skip the whole PDF')
    ranges = []
    start = end = keep[0]
    for page in keep[1:]:
        if page == end + 1:
            end = page
        else:
            ranges.append(str(start) if start == end else f'{start}-{end}')
            start = end = page
    ranges.append(str(start) if start == end else f'{start}-{end}')
    return ','.join(ranges)
