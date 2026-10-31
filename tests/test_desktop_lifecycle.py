import time
from viralogix.desktop import Session, atomic
from viralogix.store import Store

def test_close_only_selected_session(tmp_path):
    store=Store(tmp_path/'workspace')
    roots=[tmp_path/'first',tmp_path/'second']
    for root in roots: root.mkdir()
    first=Session(store,roots[0],'a'*32)
    second=Session(store,roots[1],'b'*32)
    for session in (first,second):
        atomic(session.root/'heartbeat.json',{'session':session.key,'time':time.time()})
        assert not session.tick('http://127.0.0.1:8502',True)
    atomic(first.root/'request.json',{'session':first.key,'nonce':'close1','action':'close'})
    assert first.tick('http://127.0.0.1:8502',True)
    assert not second.tick('http://127.0.0.1:8503',True)
    assert second.phase=='ready'

def test_lost_supervisor_stops_session(tmp_path):
    session=Session(Store(tmp_path/'workspace'),tmp_path,'c'*32)
    session.started=time.time()-60
    assert session.tick('',False)
