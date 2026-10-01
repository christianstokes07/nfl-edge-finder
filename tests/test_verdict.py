import json
from pathlib import Path

from src import verdict

CASES = json.loads(Path(__file__).with_name("fixtures").joinpath("verdict_cases.json").read_text())


def test_verdict_cases():
    # the same file is checked against site/analytics.js in tests/analytics.test.js
    for c in CASES:
        got = verdict.verdict(c["stat"], c["side"], c["line"], c["proj"], c.get("market_p"))
        assert got == c["want"], c
