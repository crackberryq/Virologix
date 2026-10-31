#!/usr/bin/env bash
# Install/update the interface only; never modifies sample data.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_BIN="${CONDA_EXE:-}"
if [[ ! -x "$CONDA_BIN" ]]; then CONDA_BIN="$(command -v conda || true)"; fi
if [[ ! -x "$CONDA_BIN" ]]; then
  for candidate in "$HOME/miniconda3/bin/conda" "$HOME/miniforge3/bin/conda" "$HOME/anaconda3/bin/conda"; do
    if [[ -x "$candidate" ]]; then CONDA_BIN="$candidate"; break; fi
  done
fi
if [[ ! -x "$CONDA_BIN" ]]; then
  echo 'Conda was not found. Install Miniforge/Miniconda or set CONDA_EXE to its executable.' >&2
  exit 1
fi
PREFIX="$HOME/.local/share/viralogix/env"
echo '[1/4] Checking the separate Viralogix environment'
if [[ ! -x "$PREFIX/bin/python" ]]; then
  "$CONDA_BIN" create --yes --prefix "$PREFIX" --override-channels --channel conda-forge python=3.12 pip
fi
echo '[2/4] Installing Viralogix'
"$PREFIX/bin/python" -m pip install --upgrade "$ROOT"
"$PREFIX/bin/python" -m pip check
echo '[3/4] Creating launch and update commands'
mkdir -p "$HOME/.local/bin"
printf '#!/usr/bin/env bash\nexec %q -m viralogix.cli serve "$@"\n' "$PREFIX/bin/python" > "$HOME/.local/bin/viralogix"
printf '#!/usr/bin/env bash\nexec %q -m viralogix.cli update "$@"\n' "$PREFIX/bin/python" > "$HOME/.local/bin/viralogix-update"
chmod +x "$HOME/.local/bin/viralogix" "$HOME/.local/bin/viralogix-update"
echo '[4/4] Checking installation'
"$PREFIX/bin/python" -m viralogix.cli doctor
echo 'Ready. Launch: ~/.local/bin/viralogix'
echo 'Then open http://localhost:8502. Stop with Ctrl+C before updating.'
