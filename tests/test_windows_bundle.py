import importlib.util
from pathlib import Path
import zipfile


def test_windows_bundle_uses_the_app_icon_and_reviewed_installer(tmp_path):
    root = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location('windows_bundle', root / 'scripts/build_windows_bundle.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    archive = module.build(root, tmp_path / 'desktop.zip')
    with zipfile.ZipFile(archive) as package:
        for name in ('brand.png','brand.ico'):
            assert package.read('Viralogix/'+name) == (root / 'src/viralogix/assets' / name).read_bytes()
        assert package.read('Viralogix/install_viralogix.py') == (root / 'scripts/install_viralogix.py').read_bytes()
        assert 'Viralogix/Viralogix-Setup.cmd' in package.namelist()
        script = package.read('Viralogix/Viralogix.ps1').decode()
        assert '--shutdown' not in script and '--terminate' not in script
        assert 'Stop-Process -Name' not in script and 'taskkill' not in script
    assert archive.read_bytes() == module.build(root, tmp_path / 'again.zip').read_bytes()
