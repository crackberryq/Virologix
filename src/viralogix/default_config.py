"""Guided workspace defaults with optimistic, atomic saves."""
from __future__ import annotations

import json

from . import run_config
from .databases import revision
from .runs import template


def edit(store, tool, payload, save=False):
    original = store.get('configs', tool, template(tool))
    loaded = 'text' not in payload
    text = payload.get('text', original)
    if not isinstance(text, str):
        raise ValueError('Provide configuration as YAML text.')
    view = payload.get('view', 'settings')
    if view not in {'settings', 'yaml'}:
        raise ValueError('Choose settings or YAML.')
    expected = revision(original) if loaded else payload.get('revision')
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError('Reload saved defaults before editing this configuration.')
    text = run_config.compile_config(tool, text, payload.get('changes'))
    if save or payload.get('validate'):
        run_config.validate(tool, text)
    if save:
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT body FROM items WHERE kind='configs' AND id=?", (tool,)).fetchone()
            actual = json.loads(row[0]) if row else template(tool)
            if revision(actual) != expected:
                raise ValueError('Saved defaults changed while you were editing. Download your edits or reload saved defaults before saving.')
            db.execute("INSERT INTO items VALUES ('configs',?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
                       (tool, json.dumps(text)))
        expected = revision(text)
    result = {'default_config': run_config.editor(tool, text) | {'revision': expected},
              'default_config_view': view, 'default_config_loaded': loaded, 'default_config_saved': save,
              'keep_modal': True, 'message': 'Defaults saved for future drafts.' if save else
              'Settings checked. Each new run still needs its native dry-run.' if payload.get('validate') else ''}
    if payload.get('download'):
        result['download'] = {'name': tool + '-config.yaml', 'text': text, 'type': 'text/yaml'}
    return result
