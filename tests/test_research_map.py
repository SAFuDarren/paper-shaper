"""Scientific-record invariants on explicitly synthetic sources, no model calls."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_map as rm


class ResearchRecords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "main.tex").write_text("\\input{parts/result}\n\\bibliography{refs}\n", encoding="utf-8")
        (self.root / "parts").mkdir()
        (self.root / "figures").mkdir()
        (self.root / "parts/result.tex").write_text("\\begin{theorem}[Synthetic]\\label{thm:toy}\nFixture only.\n\\end{theorem}\n\\input{figures/flow}\n\\cite{real_fixture,missing}\n", encoding="utf-8")
        (self.root / "figures/flow.tex").write_text("Synthetic figure.\n", encoding="utf-8")
        (self.root / "refs.bib").write_text("@misc{real_fixture,title={Synthetic only}}\n", encoding="utf-8")
        (self.root / "unselected.tex").write_text("\\begin{theorem}NOT IN SCOPE\\end{theorem}", encoding="utf-8")
        self.inv, self.map, self.plans = [self.root / n for n in ("inventory.json", "map.json", "plans.json")]
        self.inventory = rm.index(self.root, ["main.tex"], follow_tex=True)
        rm.save(self.inv, self.inventory)
        self.data = rm.template(self.inv)
        self.data["project"] = {k: "Synthetic only" for k in self.data["project"]}
        self.data["coverage_limits"] = ["Selected synthetic input closure only"]
        for f in self.data["files"]:
            lines = next(r["lines"] for r in self.inventory["files"] if r["path"] == f["path"])
            f.update(disposition="read", ranges=[[1, lines]], reason="Fixture inspected")
        ref = {"path": "parts/result.tex", "start": 1, "end": 3, "role": "fixture", "check": "read"}
        self.data["claims"] = [dict(id=i, kind="fixture", statement="Synthetic only", scope="Fixture", status="finite_check", caveats=["Not science"], sources=[ref]) for i in ("A", "B")]
        for c in self.data["coverage"]:
            c.update(disposition="claim", claim_ids=["A"], reason="Synthetic candidate")
        self.data["links"] = [dict(id="L1", **{"from": ["A"]}, to="B", relation="derives", status="supported", rationale="Synthetic connection, no scientific claim", sources=[ref])]
        rm.save(self.map, self.data)
        self.plan_data = {"version": "1", "research_map_sha256": rm.core.digest(self.map), "options": [dict(id="P", question="Fixture", contribution="Fixture", central_claim="B", claim_ids=["A", "B"], steps=["L1"], baseline_sources=[ref], emphasis="Fixture", tradeoffs="Fixture", open_items=[], assertion="supported")]}

    def check(self, data=None, plans=False):
        rm.save(self.map, self.data if data is None else data)
        if plans:
            self.plan_data["research_map_sha256"] = rm.core.digest(self.map)
            rm.save(self.plans, self.plan_data)
        return rm.validate(self.inv, self.map, mainlines=self.plans if plans else None)

    def test_real_include_closure_and_missing_citation_are_explicit(self):
        self.assertEqual(len(self.inventory["files"]), 4)
        self.assertEqual(self.inventory["missing_includes"], [])
        self.assertEqual([c["key"] for c in self.inventory["unresolved_citations"]], ["missing"])
        self.assertEqual(self.inventory["candidates"][0]["key"], "thm:toy")
        report = self.check(plans=True)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["warnings"])

    def test_candidate_omission_is_an_error(self):
        self.data["coverage"] = []
        self.assertIn("candidate unaccounted", " ".join(self.check()["errors"]))

    def test_file_omission_is_an_error(self):
        self.data["files"].pop()
        self.assertIn("file unaccounted", " ".join(self.check()["errors"]))

    def test_sources_changed_after_index_fail(self):
        (self.root / "refs.bib").write_text("changed", encoding="utf-8")
        self.assertIn("source missing/changed", " ".join(self.check()["errors"]))

    def test_source_range_must_be_inside_actual_read_declaration(self):
        row = next(f for f in self.data["files"] if f["path"] == "parts/result.tex")
        row["ranges"] = [[1, 1]]
        self.assertIn("outside declared reading", " ".join(self.check()["errors"]))

    def test_unknown_source_and_claim_are_rejected(self):
        self.data["claims"][0]["sources"][0] = {"path": "absent", "start": 1, "end": 1}
        self.data["links"][0]["to"] = "MISSING"
        errors = " ".join(self.check()["errors"])
        self.assertIn("unindexed source", errors)
        self.assertIn("unknown claim endpoint", errors)

    def test_derivation_cycle_is_rejected(self):
        link = copy.deepcopy(self.data["links"][0])
        link.update(id="L2", to="A", **{"from": ["B"]})
        self.data["links"].append(link)
        with self.assertRaisesRegex(ValueError, "derivation cycle"):
            self.check()

    def test_gap_cannot_support_a_declared_supported_mainline(self):
        self.data["links"][0]["status"] = "gap"
        self.assertTrue(self.check()["ok"])
        self.assertIn("declared reasoning gap", " ".join(self.check(plans=True)["errors"]))
        self.plan_data["options"][0]["assertion"] = "proposal"
        self.assertTrue(self.check(plans=True)["ok"])

    def test_conditional_bridge_requires_a_conditional_or_proposal_option(self):
        self.data["links"][0]["status"] = "conditional"
        self.assertIn("conditional step", " ".join(self.check(plans=True)["errors"]))
        self.plan_data["options"][0]["assertion"] = "conditional"
        self.assertTrue(self.check(plans=True)["ok"])

    def test_motivation_or_limitation_is_not_a_supporting_step(self):
        for relation in ["motivates", "limits", "implements", "compares"]:
            self.data["links"][0]["relation"] = relation
            self.assertIn("evidence relation", " ".join(self.check(plans=True)["errors"]))

    def test_excluded_file_cannot_be_claimed_as_read_source(self):
        row = next(f for f in self.data["files"] if f["path"] == "parts/result.tex")
        row["disposition"] = "excluded"
        self.assertIn("outside declared reading", " ".join(self.check()["errors"]))

    def test_supported_claim_needs_an_inspected_source(self):
        for claim in self.data["claims"]:
            for source in claim["sources"]:
                source["check"] = "not_checked"
        self.assertIn("no inspected source", " ".join(self.check(plans=True)["errors"]))

    def test_supported_mainline_cannot_use_open_claim(self):
        self.data["claims"][1]["status"] = "open"
        self.assertIn("unresolved/refuted", " ".join(self.check(plans=True)["errors"]))

    def test_missing_or_disconnected_mainline_step_fails(self):
        self.plan_data["options"][0]["steps"] = ["missing"]
        errors = " ".join(self.check(plans=True)["errors"])
        self.assertIn("missing reasoning step", errors)
        self.assertIn("no selected reasoning step reaches", errors)

    def test_old_inventory_or_map_hash_cannot_be_reused(self):
        self.data["inventory_sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "inventory hash"):
            self.check()
        self.data["inventory_sha256"] = rm.core.digest(self.inv)
        rm.save(self.map, self.data)
        rm.save(self.plans, self.plan_data)
        self.data["project"]["progress"] = "Changed research"
        rm.save(self.map, self.data)
        with self.assertRaisesRegex(ValueError, "not bound"):
            rm.validate(self.inv, self.map, mainlines=self.plans)

    def test_index_cannot_read_outside_root(self):
        with self.assertRaisesRegex(ValueError, "escapes"):
            rm.index(self.root, ["../"])

    def test_unresolved_candidate_remains_visible(self):
        self.data["coverage"][0].update(disposition="unresolved", claim_ids=[], reason="Needs author context")
        report = self.check()
        self.assertTrue(report["ok"])
        self.assertIn("unresolved candidate", " ".join(report["warnings"]))

    def test_template_never_invents_reading_or_results(self):
        data = rm.template(self.inv)
        self.assertEqual(data["claims"], [])
        self.assertTrue(all(f["disposition"] == "pending" and f["ranges"] == [] for f in data["files"]))

    def test_custom_ids_are_locators_not_verified_claims(self):
        source = self.root / "ledger.md"
        source.write_text("M42 earlier\nM42 repeated\nM43 next\n", encoding="utf-8")
        indexed = rm.index(self.root, ["ledger.md"], [r"\bM\d+\b"])
        self.assertEqual([c["key"] for c in indexed["candidates"]], ["M42", "M43"])
        self.assertNotIn("claims", indexed)

    def test_index_surfaces_untracked_id_families_and_variants(self):
        source = self.root / "ledger.md"
        source.write_text("M01 M05-CF T05 T06 B01 C02 O01\n", encoding="utf-8")
        indexed = rm.index(self.root, ["ledger.md"], [r"\bM\d{2}\b"])
        hints = {r["prefix"]: r for r in indexed["id_family_hints"]}
        self.assertEqual(hints["M"]["unmatched_examples"], ["M05-CF"])
        self.assertEqual(hints["T"]["unmatched_count"], 2)
        self.assertEqual(hints["B"]["unmatched_examples"], ["B01"])
        self.assertEqual({c["key"] for c in indexed["candidates"]}, {"M01", "M05"})
        self.assertNotIn("claims", indexed)

    def test_malformed_json_cli_has_no_traceback(self):
        self.map.write_text("[]", encoding="utf-8")
        p = subprocess.run([sys.executable, rm.__file__, "check", str(self.inv), str(self.map)], capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(json.loads(p.stderr)["ok"])
        self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main()
