"""Rebuild stored cells without discarding their recorded source metadata."""
from collections import defaultdict
from backend.services.table_utils import rebuild_structured_tables


def rebuild_page_tables(rows, chunks):
    metadata = defaultdict(list)
    for chunk in chunks:
        item = chunk.metadata_ or {}
        if item.get('source_kind') == 'table_csv' and item.get('table_name'):
            metadata[item['table_name']].append(item)
    grouped = {}
    for row in rows:
        # Distinct stored table names and physical pages must not be merged by
        # a shortened display name. Header disagreements also remain separate.
        key = (row.table_name, row.source_page, tuple(row.headers or []))
        grouped.setdefault(key, []).append(row)
    result = []
    for (name, page, headers), records in grouped.items():
        candidates = metadata.get(name, [])
        for table in rebuild_structured_tables(name or 'untitled_table', list(headers), [r.row_data or {} for r in records]):
            table['page'] = page
            bound = []
            for rebuilt in table.get('rows', []):
                matches = [r for r in records if list(table.get('headers', [])) == list(headers)
                           and [(r.row_data or {}).get(h, '') for h in headers] == rebuilt]
                bound.append(matches[0] if len(matches) == 1 else None)
            table['source_row_indices'] = [r.row_index if r else None for r in bound]
            table['stored_row_units'] = [r.unit if r else None for r in bound]
            for key, attr in (('source_provider', 'source_provider'), ('source_sha256', 'source_sha256'),
                              ('quality_status', 'quality_status')):
                values = {getattr(r, attr, None) for r in records}
                table[key] = next(iter(values)) if len(values) == 1 else None
            # Only metadata captured for this exact stored table can restore
            # its caption/unit/region. Missing or conflicting metadata stays
            # unknown; neither a label nor a neighboring table supplies it.
            for key, stored_key in (('title', 'table_title'), ('unit', 'unit'), ('region', 'region'),
                                    ('crop_box', 'crop_box'), ('rotation', 'rotation'),
                                    ('header_source_page', 'header_source_page'), ('header_repairs', 'header_repairs')):
                values = [m[stored_key] for m in candidates if m.get(stored_key) is not None]
                if values and all(v == values[0] for v in values):
                    table[key] = values[0]
            result.append(table)
    return result
