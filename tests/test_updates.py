import io
import pytest
from viralogix import updates

def test_update_pins_commit_and_checks_environment(monkeypatch):
    sha = 'a' * 40
    monkeypatch.setattr(updates, 'urlopen', lambda *a, **kw: io.StringIO('{"sha":"' + sha + '"}'))
    calls = []
    monkeypatch.setattr(updates.subprocess, 'run', lambda argv, **kw: calls.append(argv))
    updates.update()
    assert calls[0][-1] == f'https://github.com/crackberryq/Virologix/archive/{sha}.zip'
    assert all(c[0] == updates.sys.executable for c in calls)
    assert calls[-1][-2:] == ['pip', 'check']

def test_bad_commit_never_installs(monkeypatch):
    monkeypatch.setattr(updates, 'urlopen', lambda *a, **kw: io.StringIO('{"sha":"bad"}'))
    monkeypatch.setattr(updates.subprocess, 'run', lambda *a, **kw: pytest.fail('Must not install'))
    with pytest.raises(ValueError): updates.update()
