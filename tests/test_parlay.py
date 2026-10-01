"""The parlay math (site/parlay.js) and the "Why this pick" logic (site/analytics.js) run in the page.
Their tests are tests/*.test.js; this runs them under pytest when Node is installed."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("name", ["parlay.test.js", "analytics.test.js"])
def test_js(name):
    test = Path(__file__).with_name(name)
    r = subprocess.run(["node", str(test)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
