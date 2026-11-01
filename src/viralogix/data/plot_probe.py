"""Exercise NanoPlot's renderer with synthetic numeric arrays, never sample data."""
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import plotly
from nanoplotter.nanoplotter_main import scatter


with TemporaryDirectory(prefix='viralogix-plot-check-') as folder:
    rng = np.random.default_rng(42)
    scatter(x=pd.Series(rng.uniform(1, 100, 120)), y=pd.Series(rng.uniform(1, 20, 120)),
            legacy={}, names=['X', 'Y'], path=str(Path(folder) / 'test'),
            plots={'dot': True, 'kde': True}, color='#4CB391', colormap='Greens',
            settings={'no_static': False, 'format': ['png'], 'dpi': 100})
    for name in ('test_dot', 'test_kde'):
        html, png = Path(folder) / (name + '.html'), Path(folder) / (name + '.png')
        if not html.is_file() or html.stat().st_size == 0:
            raise RuntimeError('NanoPlot did not generate ' + name + '.html')
        if not png.is_file() or not png.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('NanoPlot did not generate a PNG for ' + name)
print('PASS: NanoPlot scatter and density HTML/PNG rendering; Plotly ' + plotly.__version__)
