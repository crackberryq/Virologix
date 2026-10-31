from pathlib import Path
import pytest
from viralogix.cfasta import parse, export_consensus
from viralogix.store import Store, workspace
from viralogix.samples import register

DEMO = (Path(__file__).parents[1]/"examples/demo.cfasta").read_text()

def test_export():
    entries=parse(DEMO)
    assert export_consensus(entries)==">VG000001 sample=DEMO|segment=SEGMENT_A\nATGCTACGAT\n"

@pytest.mark.parametrize("old,new", [("length=10","length=11"),("3:G>A","3:A>G"),("0.7","nan"),("3-6","3-11"),("LOCAL","GLOBAL"),("3:G>A","6:-2"),("3:G>A","3:G>A;3:G>T")])
def test_invalid(old,new):
    with pytest.raises(ValueError): parse(DEMO.replace(old,new))

def test_empty_table_allowed():
    assert len(parse(DEMO.split("H1\t")[0])[0].haplotypes)==0

def test_duplicate_entry():
    with pytest.raises(ValueError): parse(DEMO+DEMO)

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
    for page in ["Samples","cFASTA","Setup"]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception
