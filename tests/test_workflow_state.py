"""Synthetic record tests. All approval messages here are fixtures, never user authority."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workflow_state.py"
SPEC = importlib.util.spec_from_file_location("workflow_state", SCRIPT)
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


class WorkflowChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = workflow.initial_state(self.base)

    def node(self, nid):
        return next(n for n in self.state["nodes"] if n["id"] == nid)

    def complete(self, nid):
        node = self.node(nid)
        name = nid.replace(":", "_") + ".md"
        (self.base / name).write_text("Synthetic artifact for " + nid, encoding="utf-8")
        node["artifacts"] = [{"path": name, "sha256": workflow.digest(self.base / name)}]
        node["self_check"] = {"performed": True, "summary": "Synthetic check fixture"}
        node["decision_summary"] = "Synthetic human decision fixture; not actual authority"
        node["status"] = "approved"
        node["approval"] = {"actor": "user", "message_ref": "test-fixture-only",
                            "user_quote": "synthetic approval, not real user approval",
                            "scope": nid, "snapshot_sha256": workflow.snapshot(self.state, nid)}

    def baseline(self, units=("intro",)):
        self.state["units"] = [{"id": u, "title": u} for u in units]
        for nid in workflow.REQUIRED:
            self.complete(nid)

    def add_plan(self, unit="intro"):
        node = workflow.new_node("R06", unit)
        self.state["nodes"].append(node)
        self.complete(node["id"])

    def authorize(self, units=("intro",)):
        self.state["mode"] = "guided_writing"
        self.state["writing_authority"] = {
            u: {"message_ref": "test-fixture-only", "user_quote": "synthetic writing authority",
                "scope": u, "method": "bounded_ai_draft"} for u in units}

    def errors(self):
        return workflow.validate(self.state, self.base)

    def test_initial_state_has_no_approvals_and_starts_at_goal(self):
        self.assertFalse(self.errors())
        result = workflow.report(self.state, self.base)
        self.assertEqual(result["current"]["id"], "R01")
        self.assertTrue(all(n["approval"] is None for n in self.state["nodes"]))

    def test_concrete_delivery_is_still_waiting_until_human_review(self):
        self.complete("R01")
        node = self.node("R01")
        node["status"] = "awaiting_review"
        node["approval"] = None
        self.assertFalse(self.errors())
        self.assertEqual(workflow.report(self.state, self.base)["action"], "wait for human review")

    def test_next_round_cannot_work_before_prerequisite_is_approved(self):
        self.node("R02")["status"] = "working"
        self.assertTrue(any("prerequisite not approved" in e for e in self.errors()))

    def test_ai_approval_record_does_not_pass(self):
        self.complete("R01")
        self.node("R01")["approval"]["actor"] = "assistant"
        self.assertTrue(any("human approval" in e for e in self.errors()))

    def test_changed_approved_artifact_is_detected(self):
        self.complete("R01")
        (self.base / "R01.md").write_text("changed after review", encoding="utf-8")
        self.assertTrue(any("changed artifacts" in e for e in self.errors()))

    def test_changed_input_is_detected(self):
        source = self.base / "source.txt"
        source.write_text("original", encoding="utf-8")
        self.node("R01")["inputs"] = [{"path": "source.txt", "sha256": workflow.digest(source)}]
        self.complete("R01")
        source.write_text("changed", encoding="utf-8")
        self.assertTrue(any("changed inputs" in e for e in self.errors()))

    def test_new_parent_approval_does_not_silently_reapprove_old_child(self):
        self.complete("R01")
        self.complete("R02")
        self.node("R01")["revision"] += 1
        self.node("R01")["decision_summary"] = "new synthetic decision"
        self.node("R01")["approval"]["snapshot_sha256"] = workflow.snapshot(self.state, "R01")
        self.assertTrue(any("R02: approval snapshot changed" in e for e in self.errors()))

    def test_unresolved_blocker_cannot_be_approved(self):
        self.node("R01")["blocking_issues"] = ["missing actual goal decision"]
        self.complete("R01")
        self.assertTrue(any("blockers" in e for e in self.errors()))

    def test_plan_only_stops_after_all_declared_plans(self):
        self.baseline(("intro", "results"))
        self.add_plan("intro")
        self.add_plan("results")
        self.assertFalse(self.errors())
        self.assertEqual(workflow.report(self.state, self.base)["action"], "planning complete; stop without drafting")

    def test_plan_only_rejects_writing_nodes(self):
        self.baseline()
        self.add_plan()
        self.state["nodes"].append(workflow.new_node("R07", "intro"))
        self.assertTrue(any("forbidden in plan_only" in e for e in self.errors()))

    def test_writing_needs_matching_approved_section_plan(self):
        self.baseline(("intro", "results"))
        self.add_plan("intro")
        self.state["nodes"].append(workflow.new_node("R06", "results"))
        self.authorize(("results",))
        write = workflow.new_node("R07", "results")
        write["status"] = "working"
        self.state["nodes"].append(write)
        self.assertTrue(any("prerequisite not approved: R06:results" in e for e in self.errors()))

    def test_writing_authority_does_not_expand_to_other_units(self):
        self.baseline(("intro", "results"))
        self.add_plan("intro")
        self.add_plan("results")
        self.authorize(("intro",))
        write = workflow.new_node("R07", "results")
        self.state["nodes"].append(write)
        self.assertTrue(any("this unit has no writing authority" in e for e in self.errors()))

    def test_final_review_requires_every_declared_unit(self):
        self.baseline(("intro", "results"))
        self.add_plan("intro")
        self.add_plan("results")
        self.authorize(("intro", "results"))
        self.state["nodes"].append(workflow.new_node("R07", "intro"))
        self.complete("R07:intro")
        final = workflow.new_node("R08")
        final["depends_on"] = ["R07:intro"]
        self.state["nodes"].append(final)
        self.assertTrue(any("missing prerequisite R07:results" in e for e in self.errors()))

    def test_authorized_writing_and_final_review_can_complete(self):
        self.baseline()
        self.add_plan()
        self.authorize()
        self.state["nodes"].append(workflow.new_node("R07", "intro"))
        self.complete("R07:intro")
        final = workflow.new_node("R08")
        final["depends_on"] = ["R07:intro"]
        self.state["nodes"].append(final)
        self.complete("R08")
        self.assertFalse(self.errors())
        self.assertIn("no submission implied", workflow.report(self.state, self.base)["action"])

    def test_inputs_can_live_in_project_outside_the_paper_work_directory(self):
        project = self.base / "project"
        project.mkdir()
        source = project / "result.txt"
        source.write_text("existing research result", encoding="utf-8")
        self.state["project_root"] = str(project)
        self.node("R01")["inputs"] = [{"path": "result.txt", "sha256": workflow.digest(source)}]
        self.complete("R01")
        self.assertFalse(self.errors())

    def test_changing_unit_list_invalidates_architecture_approval(self):
        self.baseline()
        self.state["units"].append({"id": "results", "title": "Results"})
        self.assertTrue(any("R05: approval snapshot changed" in e for e in self.errors()))

    def test_cycles_and_duplicates_are_rejected(self):
        self.node("R01")["depends_on"] = ["R02"]
        self.assertTrue(any("dependency cycle" in e for e in self.errors()))
        self.state["nodes"].append(copy.deepcopy(self.node("R01")))
        self.assertTrue(any("unique" in e for e in self.errors()))

    def test_paths_cannot_escape_evidence_roots(self):
        self.node("R01")["inputs"] = [{"path": "../outside", "sha256": "x"}]
        self.complete("R01")
        self.assertTrue(any("escapes" in e for e in self.errors()))

    def test_init_does_not_overwrite_existing_progress(self):
        directory = self.base / "cli"
        first = subprocess.run([sys.executable, str(SCRIPT), "init", str(directory)], capture_output=True)
        target = directory / "workflow-state.json"
        before = target.read_bytes()
        second = subprocess.run([sys.executable, str(SCRIPT), "init", str(directory)], capture_output=True)
        self.assertEqual(first.returncode, 0)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(before, target.read_bytes())


if __name__ == "__main__":
    unittest.main()
