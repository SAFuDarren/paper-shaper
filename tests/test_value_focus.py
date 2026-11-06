"""Evidence binding and emphasis checks using synthetic records only."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import value_focus


class ValueFocusChecks(unittest.TestCase):
    def test_central_claim_cannot_use_selected_result_as_a_decoy(self):
        focus = {"sha256": "approved", "selected": [{"id": "V1", "claim_ids": ["C1"]}]}
        data = {"author_focus_sha256": "approved", "options": [{"focus_ids": ["V1"], "claim_ids": ["C1", "C2"], "central_claim": "C2"}]}
        with self.assertRaisesRegex(ValueError, "central_claim"):
            value_focus.mainline_binding(data, focus)
        data["options"][0]["central_claim"] = "C1"
        value_focus.mainline_binding(data, focus)
        data["author_focus_sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "approved author focus"):
            value_focus.mainline_binding(data, focus)

    def test_each_declared_focus_needs_result_support(self):
        focus = {"sha256": "approved", "selected": [{"id": "V1", "claim_ids": ["C1"]}, {"id": "V2", "claim_ids": ["C2"]}]}
        data = {"author_focus_sha256": "approved", "options": [{"focus_ids": ["V1", "V2"], "claim_ids": ["C1"], "central_claim": "C1"}]}
        with self.assertRaisesRegex(ValueError, "do not address"):
            value_focus.mainline_binding(data, focus)
        for refs in [["V3"], ["V1"]]:
            data["options"][0]["focus_ids"] = refs
            with self.assertRaisesRegex(ValueError, "author-selected"):
                value_focus.mainline_binding(data, focus)

    def test_value_analysis_binds_evidence_and_keeps_recommendations_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            research = root / "research.json"
            analysis = root / "value.json"
            research.write_text(json.dumps({"claims": [{"id": "C1"}]}), encoding="utf-8")
            data = {"version": "1", "research_map_sha256": value_focus.core.digest(research), "options": [dict(id="V1", label="Synthetic", claim_ids=["C1"], baseline="Old", advance="New", value_case="Synthetic", scope_costs="Synthetic")], "recommended_ids": ["V1"], "recommendation_reason": "AI fixture only"}
            analysis.write_text(json.dumps(data), encoding="utf-8")
            self.assertNotIn("author_focus", value_focus.validate(analysis, research))
            for field, value in [("research_map_sha256", "changed"), ("recommended_ids", ["V2"])]:
                changed = copy.deepcopy(data)
                changed[field] = value
                analysis.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    value_focus.validate(analysis, research)
