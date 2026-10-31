"""Build the Windows bootstrap from reviewed source and the app's own brand."""
from pathlib import Path
import zipfile


def build(root, destination):
    root, destination = Path(root), Path(destination)
    files = {p.name: p for p in (root / 'scripts/windows').glob('*') if p.suffix in {'.ps1', '.cmd', '.vbs'}}
    files.update({name: root / 'src/viralogix/assets' / name for name in ('brand.ico', 'brand.png')})
    files['install_viralogix.py'] = root / 'scripts/install_viralogix.py'
    files['README.txt'] = root / 'docs/windows-desktop.txt'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            info = zipfile.ZipInfo('Viralogix/' + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return destination


if __name__ == '__main__':
    build(Path(__file__).resolve().parents[1], Path('dist/Viralogix-Windows.zip'))
