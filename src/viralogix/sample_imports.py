"""Bounded sample-table review and transactional registration, without reading inputs."""
from __future__ import annotations
import csv
import hashlib
import io
import json
from .store import now

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 500
COLUMNS = {'sample_id', 'input_folder', 'read_mode'}
MODES = {'supplied_records', 'hybrid', 'ont_only', 'illumina_only'}


def review(store, text, registrations=None):
    from .runs import absolute_path, valid_id
    if not isinstance(text, str) or len(text.encode()) > MAX_BYTES:
        raise ValueError('Provide a CSV/TSV table no larger than 2 MB.')
    existing = store.all('samples') if registrations is None else registrations
    registered = {s['id'].casefold() for s in existing}
    result = {'schema': 1, 'checked_at': now(), 'rows': [], 'errors': [], 'can_import': False,
              'token': None, 'ready_count': 0, 'invalid_count': 0,
              'notice': 'Folder existence checked; input contents are not read or validated. Import rechecks this review and registers all rows together. Original files stay in place; no jobs start.'}
    delimiter = '\t' if '\t' in text.lstrip('\ufeff').partition('\n')[0] else ','
    reader = csv.reader(io.StringIO(text.lstrip('\ufeff'), newline=''), delimiter=delimiter, strict=True)
    try:
        header = [v.strip() for v in next(reader, [])]
        if not {'sample_id', 'input_folder'} <= set(header):
            result['errors'].append('Table requires sample_id and input_folder; read_mode is optional.')
        if len(set(header)) != len(header):
            result['errors'].append('Column names must be unique.')
        unknown = set(header) - COLUMNS
        if unknown:
            result['errors'].append('Unknown columns: ' + ', '.join(sorted(unknown)) + '. Use only sample_id, input_folder and optional read_mode.')
        if result['errors']:
            return result
        seen = {}
        while True:
            line = reader.line_num + 1
            fields = next(reader, None)
            if fields is None:
                break
            if not any(v.strip() for v in fields):
                continue
            if len(result['rows']) >= MAX_ROWS:
                result['errors'].append('Table exceeds 500 sample rows. Split it into smaller tables.')
                break
            values = dict(zip(header, fields))
            sid = values.get('sample_id', '').strip()
            raw_path = values.get('input_folder', '').strip()
            mode = values.get('read_mode', '').strip() or 'supplied_records'
            row = {'line': line, 'id': sid, 'input_folder': raw_path, 'path': None, 'mode': mode, 'errors': []}
            result['rows'].append(row)
            if len(fields) != len(header):
                row['errors'].append('Field count does not match the header. Check delimiters and quoting.')
            try:
                valid_id(sid)
            except ValueError as exc:
                row['errors'].append(str(exc))
            if sid.casefold() in registered:
                row['errors'].append('Sample ID is already registered (case-insensitive).')
            if sid.casefold() in seen:
                first = seen[sid.casefold()]
                message = 'Duplicate sample ID in this table (case-insensitive).'
                if message not in first['errors']:
                    first['errors'].append(message)
                row['errors'].append(message)
            else:
                seen[sid.casefold()] = row
            if mode not in MODES:
                row['errors'].append('Input mode must be supplied_records (or a supported legacy read mode).')
            try:
                path = absolute_path(raw_path)
                row['path'] = str(path)
                if not path.is_dir():
                    row['errors'].append('Input folder does not exist or is not accessible.')
            except (ValueError, OSError, RuntimeError) as exc:
                row['errors'].append('Invalid input folder: ' + str(exc))
    except csv.Error as exc:
        result['errors'].append('Malformed CSV/TSV near line ' + str(reader.line_num) + ': ' + str(exc))
    if not result['rows']:
        result['errors'].append('Add at least one sample row.')
    result['ready_count'] = sum(not r['errors'] for r in result['rows'])
    result['invalid_count'] = len(result['rows']) - result['ready_count']
    result['can_import'] = bool(result['rows']) and not result['errors'] and not result['invalid_count']
    if result['can_import']:
        state = sorted([{k: r.get(k) for k in ('id', 'path', 'mode')} for r in existing], key=lambda r: r['id'])
        content = {'text': text, 'rows': result['rows'], 'registered': state}
        result['token'] = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


def commit(store, text, expected=None):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = [json.loads(r[0]) for r in db.execute("SELECT body FROM items WHERE kind='samples'")]
        plan = review(store, text, existing)
        if not plan['can_import']:
            first = next((r for r in plan['rows'] if r['errors']), None)
            detail = '; '.join(plan['errors']) or ('Line ' + str(first['line']) + ': ' + '; '.join(first['errors']))
            raise ValueError('Sample table needs review. ' + detail)
        if expected is not None and expected != plan['token']:
            raise ValueError('Table, resolved folders or sample registrations changed. Preview the table again before importing.')
        created = now()
        items = [{'id': r['id'], 'path': r['path'], 'mode': r['mode'], 'created': created} for r in plan['rows']]
        for row in items:
            db.execute("INSERT INTO items(kind,id,body) VALUES ('samples',?,?)", (row['id'], json.dumps(row)))
    return items
