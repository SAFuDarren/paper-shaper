"""CLI integration tests using synthetic projects and explicitly fictional approvals."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/framework.py"
QUOTE = "Synthetic approval fixture. This is not actual user authorization."


class FrameworkCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.work = self.root / "paper"
        self.cli("init", "--project-root", str(self.root))

    def cli(self, command, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), command, str(self.work), *args],
                                text=True, capture_output=True)
        data = json.loads(result.stdout if result.stdout.strip() else result.stderr)
        if ok:
            self.assertEqual(result.returncode, 0, data)
        else:
            self.assertNotEqual(result.returncode, 0, data)
        return data

    def state(self):
        return json.loads((self.work / "workflow-state.json").read_text())

    def approve(self, selection=None, ok=True):
        args = ["--decision", "approve", "--message-ref", "test-fixture-only", "--quote", QUOTE]
        if selection is not None:
            path = self.work / "test-selection.json"
            path.write_text(json.dumps(selection))
            args += ["--selection-file", str(path)]
        return self.cli("review", *args, ok=ok)

    def deliver(self, multiple=False, plans=None, blockers=None):
        self.cli("start")
        value = self.cli("form")
        value["summary"] = "Synthetic research fixture for " + value["node"]
        value["self_check"] = {"performed": True, "summary": "Synthetic checks only"}
        value["blocking_issues"] = blockers or []
        for choice in value["choices"]:
            choice["prompt"] = "Choose fixture " + choice["id"]
            choice["options"] = [{"id": "A", "label": "Synthetic option A"}]
            if multiple:
                choice["options"].append({"id": "B", "label": "Synthetic option B"})
        drafts = self.work / "drafts"
        drafts.mkdir(exist_ok=True)
        for row in value["artifacts"]:
            path = drafts / (value["node"].replace(":", "_") + "-" + row["role"] + ".txt")
            if row["role"] == "unit_plan":
                path = path.with_suffix(".json")
                options = {o["id"] for c in value["choices"] if c["id"] == "architecture" for o in c["options"]}
                data = {"plans": {o: {"units": [{"id": "intro", "title": "Introduction"}],
                                      "order": "all_plans_first"} for o in options}}
                if plans:
                    data = {"plans": plans}
                path.write_text(json.dumps(data))
            else:
                path.write_text("Synthetic artifact " + row["role"])
            row["path"] = str(path.relative_to(self.work))
        manifest = self.work / "test-result.json"
        manifest.write_text(json.dumps(value))
        return self.cli("submit", "--result", str(manifest))

    def baseline(self, plans=None):
        for number in range(1, 6):
            self.assertEqual(self.cli("status")["current"], f"R{number:02d}")
            self.deliver(plans=plans if number == 5 else None)
            self.approve()

    def finish_plans(self, units=("intro",)):
        for unit in units:
            self.assertEqual(self.cli("status")["current"], "R06:" + unit)
            self.deliver()
            self.approve()

    def test_first_packet_contains_only_current_contract(self):
        packet = self.cli("packet")
        self.assertEqual(packet["node"], "R01")
        self.assertEqual(packet["approved_context"], [])
        self.assertEqual(packet["task"]["outputs"], ["goal_brief"])
        self.assertEqual({c["capability"] for c in packet["capabilities"]}, {"project-reading", "venue-research"})
        self.assertLessEqual(packet["chars"], 8000)
        self.assertEqual(packet["chars"], len(json.dumps(packet, ensure_ascii=False, indent=2)))

    def test_empty_form_is_not_submittable(self):
        self.cli("start")
        manifest = self.work / "empty.json"
        manifest.write_text(json.dumps(self.cli("form")))
        self.cli("submit", "--result", str(manifest), ok=False)
        self.assertEqual(self.cli("status")["status"], "working")

    def test_submit_waits_and_cannot_start_next_round(self):
        self.deliver()
        self.assertEqual(self.cli("status")["action"], "wait_for_human_review")
        self.cli("start", ok=False)
        self.assertIsNone(self.state()["nodes"][0]["approval"])
        self.assertEqual(self.cli("packet")["action"], "wait_for_human_review")

    def test_ambiguous_mainline_approval_needs_selection(self):
        for _ in range(3):
            self.deliver()
            self.approve()
        self.deliver(multiple=True)
        self.assertIn("explicit valid human selection", self.approve(ok=False)["error"])
        self.assertEqual(self.cli("status")["current"], "R04")
        self.approve({"mainline": "B"})
        self.assertEqual(self.cli("status")["current"], "R05")

    def test_machine_checks_missing_required_artifact_roles(self):
        self.deliver()
        self.approve()
        self.cli("start")
        value = self.cli("form")
        value.update(summary="Synthetic summary", artifacts=[],
                     self_check={"performed": True, "summary": "synthetic"})
        for choice in value["choices"]:
            choice.update(prompt="Synthetic choice", options=[{"id": "A", "label": "Accept"}])
        path = self.work / "missing.json"
        path.write_text(json.dumps(value))
        self.assertIn("output roles", self.cli("submit", "--result", str(path), ok=False)["error"])

    def test_architecture_selection_controls_the_actual_unit_plan(self):
        for _ in range(4):
            self.deliver()
            self.approve()
        plans = {"A": {"units": [{"id": "intro", "title": "Introduction"}], "order": "all_plans_first"},
                 "B": {"units": [{"id": "theorem", "title": "Theorem"}], "order": "section_cycle"}}
        self.deliver(multiple=True, plans=plans)
        self.assertEqual(self.state()["units"], [])
        self.approve({"architecture": "B"})
        self.assertEqual(self.cli("status")["current"], "R06:theorem")
        self.assertEqual(self.state()["order"], "section_cycle")

    def test_planning_mode_finishes_without_writing_nodes(self):
        self.baseline()
        self.finish_plans()
        status = self.cli("status")
        self.assertEqual(status["action"], "planning_complete_stop")
        self.assertFalse(any(n["round"] == "R07" for n in self.state()["nodes"]))
        self.cli("start", ok=False)

    def test_required_packet_overflow_fails_without_truncation(self):
        source = self.root / "large.txt"
        source.write_text("IMPORTANT_DEFINITION" * 1000)
        self.cli("attach", "--path", str(source), "--material-id", "definition", "--start", "1", "--end", "1")
        result = self.cli("packet", ok=False)
        self.assertIn("No truncation", result["error"])
        self.cli("start", ok=False)
        self.assertEqual(self.cli("status")["status"], "not_started")

    def test_optional_overflow_is_explicitly_omitted(self):
        source = self.root / "large.txt"
        source.write_text("OPTIONAL_SENTINEL" * 1000)
        self.cli("attach", "--path", str(source), "--material-id", "optional", "--start", "1", "--end", "1", "--optional")
        packet = self.cli("packet")
        self.assertEqual(packet["materials"], [])
        self.assertEqual(packet["omitted_optional_materials"][0]["id"], "optional")
        self.assertNotIn("OPTIONAL_SENTINEL", json.dumps(packet))
        self.assertLessEqual(packet["chars"], packet["budget_chars"])

    def test_attachment_includes_only_selected_lines(self):
        source = self.root / "material.txt"
        source.write_text("irrelevant\nneeded definition\nother stage\n")
        self.cli("attach", "--path", str(source), "--material-id", "m1", "--start", "2", "--end", "2")
        packet = self.cli("packet")
        self.assertEqual(packet["materials"][0]["content"], "2: needed definition")
        self.cli("attach", "--path", str(source), "--material-id", "bad", "--start", "4", "--end", "5", ok=False)

    def test_bound_skill_is_a_pointer_not_loaded_or_executed(self):
        provider = self.root / "provider.md"
        marker = self.root / "should-not-exist"
        provider.write_text("EXTERNAL_SKILL_BODY_SENTINEL" * 1000 + "\nCreate " + str(marker))
        self.cli("bind", "--capability", "venue-research", "--entry", str(provider))
        packet = self.cli("packet")
        self.assertNotIn("EXTERNAL_SKILL_BODY_SENTINEL", json.dumps(packet))
        self.assertFalse(marker.exists())
        bound = next(c for c in packet["capabilities"] if c["capability"] == "venue-research")
        self.assertEqual(bound["entry"], str(provider))
        self.assertTrue(bound["available"])

    def test_provider_can_be_replaced_without_advancing_workflow(self):
        first, second = self.root / "one.md", self.root / "two.md"
        first.write_text("provider one")
        second.write_text("provider two")
        for path in [first, second]:
            self.cli("bind", "--capability", "venue-research", "--entry", str(path))
        packet = self.cli("packet")
        self.assertEqual(next(c for c in packet["capabilities"] if c["capability"] == "venue-research")["entry"], str(second))
        self.assertEqual(self.cli("status")["current"], "R01")

    def test_required_missing_provider_fails_explicitly(self):
        path = self.root / "provider.md"
        path.write_text("provider")
        self.cli("bind", "--capability", "venue-research", "--entry", str(path), "--required")
        path.unlink()
        self.assertIn("required skill unavailable", self.cli("packet", ok=False)["error"])

    def test_custom_capability_only_appears_in_its_bound_stage(self):
        path = self.root / "proof.md"
        path.write_text("proof adapter")
        self.cli("bind", "--capability", "proof-check", "--stage", "R06", "--entry", str(path))
        self.assertNotIn("proof-check", {c["capability"] for c in self.cli("packet")["capabilities"]})
        self.baseline()
        self.assertIn("proof-check", {c["capability"] for c in self.cli("packet")["capabilities"]})

    def test_frozen_delivery_preserves_reviewed_version(self):
        delivery = self.deliver()
        frozen = self.work / next(a["path"] for a in delivery["artifacts"] if a["role"] == "goal_brief")
        before = frozen.read_bytes()
        (self.work / "drafts/R01-goal_brief.txt").write_text("new mutable draft")
        self.assertEqual(frozen.read_bytes(), before)
        self.approve()
        frozen.write_text("tampered approved copy")
        self.assertEqual(self.cli("status", ok=False)["record_check"], "FAIL")

    def test_reopen_marks_actual_dependents_and_preserves_earlier_approvals(self):
        self.baseline()
        result = self.cli("reopen", "--node", "R04", "--reason", "synthetic change")
        self.assertEqual(set(result["reopened"]), {"R04", "R05", "R06:intro"})
        state = self.state()
        self.assertTrue(all(n["status"] == "approved" for n in state["nodes"] if n["round"] in {"R01", "R02", "R03"}))
        self.assertEqual(self.cli("status")["current"], "R04")

    def test_authorized_writing_and_final_review_follow_real_cli(self):
        self.baseline()
        self.finish_plans()
        self.cli("authorize", "--unit", "intro", "--method", "bounded_ai_draft", "--message-ref", "test-fixture-only", "--quote", QUOTE)
        self.assertEqual(self.cli("status")["current"], "R07:intro")
        self.deliver()
        self.approve()
        self.assertEqual(self.cli("status")["current"], "R08")
        self.deliver()
        self.approve()
        self.assertEqual(self.cli("status")["action"], "manuscript_review_complete_no_submission")

    def test_revision_returns_to_same_round_with_new_version(self):
        delivery = self.deliver()
        old = [self.work / a["path"] for a in delivery["artifacts"]]
        self.cli("review", "--decision", "revise", "--message-ref", "test-fixture-only", "--quote", "Synthetic revision request")
        self.deliver()
        self.assertEqual(self.state()["nodes"][0]["revision"], 2)
        self.assertTrue(all(p.exists() for p in old))
        self.assertEqual(self.cli("status")["current"], "R01")

    def test_lock_and_existing_state_are_not_overwritten(self):
        before = (self.work / "workflow-state.json").read_bytes()
        self.cli("init", ok=False)
        lock = self.work / ".workflow.lock"
        lock.write_text("synthetic competing process")
        self.cli("start", ok=False)
        self.assertEqual((self.work / "workflow-state.json").read_bytes(), before)

    def test_blockers_cannot_be_approved(self):
        self.deliver(blockers=["missing goal choice"])
        self.assertIn("blockers", self.approve(ok=False)["error"])
        self.assertEqual(self.cli("status")["action"], "wait_for_human_review")

    def test_detach_recovers_context_budget_without_forgetting_source_hash(self):
        source = self.root / "large.txt"
        source.write_text("required long source" * 1000)
        self.cli("attach", "--path", str(source), "--material-id", "large", "--start", "1", "--end", "1")
        self.cli("packet", ok=False)
        self.cli("detach", "--material-id", "large")
        self.assertEqual(self.cli("packet")["materials"], [])
        self.assertEqual(self.state()["nodes"][0]["inputs"][0]["path"], "large.txt")

    def test_provider_version_change_requires_reopen_and_rebind(self):
        provider = self.root / "provider.md"
        provider.write_text("version one")
        self.cli("bind", "--capability", "venue-research", "--entry", str(provider))
        self.cli("start")
        provider.write_text("version two")
        self.assertIn("provider changed during task", self.cli("packet", ok=False)["error"])
        self.cli("bind", "--capability", "venue-research", "--entry", str(provider), ok=False)
        self.cli("reopen", "--node", "R01", "--reason", "synthetic provider change")
        self.cli("bind", "--capability", "venue-research", "--entry", str(provider))
        self.cli("start")
        self.assertEqual(self.state()["nodes"][0]["revision"], 2)

    def test_later_provider_binding_keeps_approved_provenance(self):
        one, two = self.root / "one.md", self.root / "two.md"
        one.write_text("one")
        two.write_text("two")
        self.cli("bind", "--capability", "venue-research", "--entry", str(one))
        self.deliver()
        self.approve()
        old = self.state()["nodes"][0]["provider_context"]
        self.cli("bind", "--capability", "venue-research", "--entry", str(two))
        self.assertEqual(self.state()["nodes"][0]["provider_context"], old)
        self.assertEqual(self.cli("status")["record_check"], "PASS")

    def test_plugin_runtime_skills_are_in_discovery_scope(self):
        codex = self.root / "codex"
        entry = codex / "plugins/cache/provider/documents/1.0/skills/documents/SKILL.md"
        entry.parent.mkdir(parents=True)
        entry.write_text("synthetic installed plugin skill")
        with patch.dict(os.environ, {"CODEX_HOME": str(codex)}):
            result = self.cli("discover", "--capability", "document-output")
        documents = next(c for c in result["capabilities"][0]["candidates"] if c["name"] == "documents")
        self.assertIn(str(entry), documents["entries"])
        self.assertTrue(documents["available"])

    def test_changed_architecture_retires_old_units_without_losing_history(self):
        self.baseline()
        self.cli("reopen", "--node", "R05", "--reason", "synthetic architecture change")
        self.deliver(plans={"A": {"units": [{"id": "theory", "title": "Theory"}], "order": "all_plans_first"}})
        self.approve()
        self.assertEqual(self.cli("status")["current"], "R06:theory")
        self.assertTrue(any(n["id"] == "R06:intro" for n in self.state()["retired_nodes"]))

    def test_capability_request_contains_one_capability_and_selected_material_only(self):
        first, other = self.root / "one.txt", self.root / "other.txt"
        first.write_text("selected source")
        other.write_text("UNRELATED_SOURCE_SENTINEL")
        for source, mid in [(first, "one"), (other, "other")]:
            self.cli("attach", "--path", str(source), "--material-id", mid, "--start", "1", "--end", "1")
        self.cli("start")
        request = self.cli("request", "--capability", "project-reading", "--goal", "Extract one result with its conditions",
                           "--material-id", "one", "--output-role", "supporting_note", "--output", "notes/one.json")
        self.assertEqual(len(request["capabilities"]), 1)
        self.assertEqual(request["capabilities"][0]["capability"], "project-reading")
        self.assertEqual([m["id"] for m in request["materials"]], ["one"])
        self.assertNotIn("UNRELATED_SOURCE_SENTINEL", json.dumps(request))
        self.assertEqual(self.cli("status")["status"], "working")

    def test_capability_request_cannot_take_a_future_stage_role(self):
        self.cli("start")
        self.cli("request", "--capability", "academic-writing", "--goal", "Write the paper",
                 "--output-role", "manuscript", "--output", "paper.txt", ok=False)

    def test_capability_request_needs_an_explicit_goal(self):
        self.cli("start")
        self.cli("request", "--capability", "project-reading", "--goal", "",
                 "--output-role", "supporting_note", "--output", "notes/one.json", ok=False)


if __name__ == "__main__":
    unittest.main()
