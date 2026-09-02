import json
from pathlib import Path

from app.services.matcher import _shortlist_candidates


GOLDEN_PATH = Path(__file__).parent / "fixtures" / "matching_golden.json"


def test_golden_matching_cases_keep_expected_candidate_first():
    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    for case in cases:
        candidates = case["candidates"] + [
            {"article": f"FILLER-{index}", "name": "Случайная позиция", "price": 1}
            for index in range(20)
        ]
        shortlist = _shortlist_candidates(case["name"], candidates)
        assert shortlist[0]["article"] == case["expected_first_article"], case["name"]
