"""Publish checked artifacts as a draft, verify GitHub checksums, then expose it."""
import hashlib
import json
import os
from pathlib import Path
import tomllib
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import quote

REPO = 'crackberryq/Virologix'
def api(path, method='GET', payload=None, binary=None):
    host = 'https://uploads.github.com/' if binary is not None else 'https://api.github.com/'
    data = binary if binary is not None else json.dumps(payload).encode() if payload is not None else None
    headers = {'Authorization': 'Bearer '+os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json',
               'Content-Type': 'application/octet-stream' if binary is not None else 'application/json'}
    try:
        with urlopen(Request(host+path, data=data, headers=headers, method=method), timeout=120) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 404 and method == 'GET': return None
        raise

def main():
    if os.environ['GITHUB_REPOSITORY'] != REPO or os.environ['GITHUB_REF'] != 'refs/heads/main':
        raise ValueError('Only this repository main branch may publish')
    version = tomllib.loads(Path('pyproject.toml').read_text())['project']['version']
    files = [Path('dist')/n for n in (f'viralogix-{version}-py3-none-any.whl', f'viralogix-{version}.tar.gz', 'Viralogix-Windows.zip')]
    receipts = {p.name: ('sha256:'+hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_size) for p in files}
    sums=Path('dist/SHA256SUMS');sums.write_text(''.join(d[7:]+'  '+n+'\n' for n,(d,_) in receipts.items()));files.append(sums)
    receipts[sums.name]=('sha256:'+hashlib.sha256(sums.read_bytes()).hexdigest(),sums.stat().st_size)
    base=f'repos/{REPO}/releases';tag='v'+version
    release=api(base+'/tags/'+tag)
    if release and not release['draft']:
        print('Already published:',release['html_url']);return
    commit=os.environ['GITHUB_SHA']
    if release and release['target_commitish'] != commit: raise ValueError('Draft belongs to another commit')
    if not release:
        notes=Path('CHANGELOG.md').read_text()
        release=api(base,'POST',{'tag_name':tag,'target_commitish':commit,'name':'Virologix '+tag,'body':notes,'draft':True,'prerelease':True})
    for p in files:
        old=next((a for a in release.get('assets',[]) if a['name']==p.name),None)
        if old:
            if (old.get('digest'),old['size']) != receipts[p.name]: raise ValueError('Conflicting draft asset')
        else: api(base+f'/{release["id"]}/assets?name='+quote(p.name),'POST',binary=p.read_bytes())
    release=api(base+'/'+str(release['id']))
    for name,receipt in receipts.items():
        asset=next(a for a in release['assets'] if a['name']==name)
        if (asset.get('digest'),asset['size']) != receipt: raise ValueError('Uploaded asset verification failed')
    result=api(base+'/'+str(release['id']),'PATCH',{'draft':False,'make_latest':'false'})
    print('Published:',result['html_url'])
if __name__=='__main__': main()
