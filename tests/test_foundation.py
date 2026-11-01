from pathlib import Path
import pytest
from viralogix.store import Store, workspace
from viralogix.samples import register

def test_independent_workspace(monkeypatch,tmp_path):
    monkeypatch.setenv("BACTOLOGIX_HOME",str(tmp_path/"bacterial"))
    monkeypatch.setenv("VIRALOGIX_HOME",str(tmp_path/"viral"))
    assert workspace()==tmp_path/"viral"
    store=Store()
    store.put("samples","x",{"id":"x"})
    assert Store().get("samples","x")=={"id":"x"}
    assert not (tmp_path/"bacterial").exists()

def test_sample_registration(tmp_path):
    store=Store(tmp_path/"workspace")
    read=tmp_path/"reads.fastq";read.write_text("@r\nA\n+\nI\n")
    register(store,"S1",str(read))
    with pytest.raises(ValueError): register(store,"S1",str(read))
    with pytest.raises(ValueError): register(store,"S2",str(read),str(read))

def test_ui(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("VIRALOGIX_HOME",str(tmp_path))
    app=AppTest.from_file(str(Path(__file__).parents[1]/"src/viralogix/app.py")).run()
    assert not app.exception
