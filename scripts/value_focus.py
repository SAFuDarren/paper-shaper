#!/usr/bin/env python3
"""Check evidence-linked value cards; author choice is a separate review action."""
import argparse
import json
from pathlib import Path
import sys

import workflow_state as core


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate(analysis_path, research_path):
    data, research = read(analysis_path), read(research_path)
    if (not isinstance(data, dict) or data.get("version") != "1"
            or data.get("research_map_sha256") != core.digest(research_path)):
        raise ValueError("value analysis must bind to the current research map")
    cards = data.get("options")
    if not isinstance(cards, list) or not cards:
        raise ValueError("value analysis needs evidence-linked options")
    ids, claims = set(), {c["id"] for c in research["claims"]}
    for card in cards:
        if (not isinstance(card, dict) or any(not core.nonempty(card.get(k)) for k in
                ["id", "label", "baseline", "advance", "value_case", "scope_costs"])
                or card["id"] in ids):
            raise ValueError("value cards need unique IDs, labels, baseline, advance, value_case and scope_costs")
        refs = card.get("claim_ids")
        if (not isinstance(refs, list) or not refs or any(not isinstance(c, str) for c in refs)
                or len(refs) != len(set(refs)) or set(refs) - claims):
            raise ValueError("value card claim_ids must name existing research records")
        ids.add(card["id"])
    recommended = data.get("recommended_ids", [])
    if (not isinstance(recommended, list) or any(not isinstance(i, str) for i in recommended)
            or len(recommended) != len(set(recommended)) or set(recommended) - ids
            or (recommended and not core.nonempty(data.get("recommendation_reason")))):
        raise ValueError("AI recommendations need valid option IDs and a reason")
    return data


def mainline_binding(data, focus):
    if not focus or data.get("author_focus_sha256") != focus["sha256"]:
        raise ValueError("mainline options must bind to the approved author focus")
    selected = {c["id"]: set(c["claim_ids"]) for c in focus["selected"]}
    for option in data["options"]:
        refs = option.get("focus_ids")
        if (not isinstance(refs, list) or not refs or any(not isinstance(i, str) for i in refs)
                or len(refs) != len(set(refs)) or set(refs) != selected.keys()):
            raise ValueError("mainline focus_ids must retain all author-selected value options; changing priorities needs R02 review")
        if any(not set(option["claim_ids"]) & selected[i] for i in refs):
            raise ValueError("mainline claims do not address the selected focus; return for author review")
        if option["central_claim"] not in set().union(*(selected[i] for i in refs)):
            raise ValueError("mainline central_claim must belong to its author-selected focus; revise value cards with the author for a new combination")


def main():
    core.configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("research_map", type=Path)
    parser.add_argument("value_analysis", type=Path)
    args = parser.parse_args()
    try:
        data = validate(args.value_analysis, args.research_map)
        print(json.dumps({"ok": True, "options": data["options"],
                          "ai_recommendation": data.get("recommended_ids", []),
                          "recommendation_reason": data.get("recommendation_reason"),
                          "author_focus": None, "next": "author_value_focus_review"}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
