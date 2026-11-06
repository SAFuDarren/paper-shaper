#!/usr/bin/env python3
"""Deterministic paper-workflow controller. No model/API/network execution."""
import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import json
import os
import platform
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid

import workflow_state as core
import value_focus

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ERROR = None
try:
    STAGES = json.loads((ROOT / "config/stages.json").read_text(encoding="utf-8-sig"))
    CAPS = json.loads((ROOT / "config/capabilities.json").read_text(encoding="utf-8-sig"))
    if (not isinstance(STAGES, dict) or not isinstance(CAPS, dict)
            or any(not isinstance(STAGES.get(f"R{i:02d}"), dict) for i in range(1, 9))):
        raise ValueError("invalid stage/capability configuration")
except (OSError, ValueError) as exc:
    CONFIG_ERROR = "incomplete or invalid skill installation; restore the complete config directory: " + str(exc)
    STAGES, CAPS = {}, {}
MUTATIONS = {"start", "attach", "detach", "retire-input", "submit", "review", "reopen", "authorize", "bind"}


class WorkflowError(ValueError):
    pass


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".workflow-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(work):
    path = work / ".workflow.lock"
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise WorkflowError("workflow is locked; check the owner process before removing a stale lock") from None
    try:
        os.write(handle, str(os.getpid()).encode())
        os.close(handle)
        yield
    finally:
        path.unlink(missing_ok=True)


def init(work, project_root):
    if not Path(project_root).is_dir():
        raise WorkflowError("project root must be an existing directory")
    work.mkdir(parents=True, exist_ok=True)
    with locked(work):
        if (work / "workflow-state.json").exists():
            raise WorkflowError("existing workflow must be resumed, not overwritten")
        state = core.initial_state(project_root)
        state.update({"framework_version": "0.2", "order": "all_plans_first",
                      "extensions": {"bindings": {}, "extra_capabilities": {}}, "events": [],
                      "research_contract": "1", "value_contract": "1"})
        write(work / "workflow-state.json", state)
    return {"created": str(work / "workflow-state.json"), "mode": "plan_only"}


def event(state, kind, node=None, **details):
    state["events"].append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            "event": kind, "node": node, **details})


def nodes(state):
    return {n["id"]: n for n in state["nodes"]}


def next_id(state):
    by_id = nodes(state)
    for nid in core.REQUIRED:
        if by_id[nid]["status"] != "approved":
            return nid
    ids = [u["id"] for u in state["units"]]
    if not ids:
        raise WorkflowError("R05 has no approved unit list")
    if state["mode"] == "plan_only" or state["order"] == "all_plans_first":
        order = ["R06:" + u for u in ids]
        if state["mode"] == "guided_writing":
            order += ["R07:" + u for u in ids]
    else:
        order = [r + ":" + u for u in ids for r in ["R06", "R07"]]
    for nid in order:
        if nid not in by_id or by_id[nid]["status"] != "approved":
            return nid
    if state["mode"] == "guided_writing" and ("R08" not in by_id or by_id["R08"]["status"] != "approved"):
        return "R08"
    return None


def get_node(state, nid, create=False):
    if nid in nodes(state):
        return nodes(state)[nid]
    r, _, unit = nid.partition(":")
    node = core.new_node(r, unit or None)
    if r == "R08":
        node["depends_on"] = ["R07:" + u["id"] for u in state["units"]]
    if create:
        state["nodes"].append(node)
    return node


def decision_keys(state, stage):
    return [k for k in STAGES[stage]["decision_keys"]
            if k != "value_focus" or state.get("value_contract") == "1"]


def choice_schema(choices, stage, state):
    if not isinstance(choices, list):
        raise WorkflowError("choices must be a list")
    keys = set()
    for row in choices:
        if not isinstance(row, dict) or not core.nonempty(row.get("id")) or row["id"] in keys:
            raise WorkflowError("choice IDs must be unique")
        keys.add(row["id"])
        options = row.get("options")
        if not core.nonempty(row.get("prompt")) or not isinstance(options, list) or not options:
            raise WorkflowError("each choice needs a prompt and concrete options")
        option_ids = [o.get("id") for o in options if isinstance(o, dict)]
        if len(option_ids) != len(options) or any(not core.nonempty(i) for i in option_ids) or len(set(option_ids)) != len(option_ids):
            raise WorkflowError("option IDs must be unique nonempty strings")
        if any(not core.nonempty(o.get("label")) for o in options):
            raise WorkflowError("options need human-readable labels")
    missing = set(decision_keys(state, stage)) - keys
    if missing:
        raise WorkflowError("missing human decision fields: " + ", ".join(sorted(missing)))


def required_outputs(state, stage):
    roles = [r for r in STAGES[stage]["outputs"]
             if r != "value_analysis" or state.get("value_contract") == "1"]
    if state.get("research_contract") == "1" and stage == "R02":
        roles += ["source_inventory", "research_map"]
    return roles


def value_choices(choices, work, artifacts):
    path = next(core.file_path(work, a["path"]) for a in artifacts if a["role"] == "value_analysis")
    cards = load(path)["options"]
    choice = next(c for c in choices if c["id"] == "value_focus")
    if (choice.get("multiple") is not True or
            {o["id"]: o["label"] for o in choice["options"]} != {c["id"]: c["label"] for c in cards}):
        raise WorkflowError("value_focus choices must match value cards and allow explicit combinations")


def author_focus(state, work):
    node = nodes(state)["R02"]
    if state.get("value_contract") != "1" or node["status"] != "approved":
        return None
    decision = json.loads(node["decision_summary"])["value_focus"]
    artifact = next(a for a in node["artifacts"] if a["role"] == "value_analysis")
    cards = {c["id"]: c for c in load(core.file_path(work, artifact["path"]))["options"]}
    focus = {"selected": [{k: cards[i][k] for k in ["id", "label", "claim_ids", "advance", "scope_costs"]}
                          for i in decision["selected"]],
             "reason": decision.get("reason"),
             "review": {"node": "R02", "message_ref": node["approval"]["message_ref"],
                        "snapshot_sha256": node["approval"]["snapshot_sha256"],
                        "value_analysis": artifact["path"]}}
    focus["sha256"] = core.packed(focus)
    return focus


def research_delivery(state, work, stage, artifacts):
    if state.get("research_contract") != "1" or stage not in {"R02", "R04"}:
        return
    from research_map import validate
    paths = {a["role"]: core.file_path(work, a["path"]) for a in artifacts}
    if stage == "R02":
        inventory, research = paths["source_inventory"], paths["research_map"]
        mainlines = None
    else:
        previous = {a["role"]: core.file_path(work, a["path"]) for a in nodes(state)["R02"]["artifacts"]}
        inventory, research = previous["source_inventory"], previous["research_map"]
        mainlines = paths["mainline_options"]
    report = validate(inventory, research, state["project_root"], mainlines)
    if state.get("value_contract") == "1" and stage == "R02":
        value_focus.validate(paths["value_analysis"], research)
    if stage == "R04" and state.get("value_contract") == "1":
        value_focus.mainline_binding(load(mainlines), author_focus(state, work))
    if not report["ok"]:
        raise WorkflowError("research records: " + "; ".join(report["errors"]))
    if stage == "R04":
        declared = {o["id"] for o in load(mainlines)["options"]}
        # Human selections must name the same concrete options that were checked.
        return declared


def checks(state, work):
    errors = core.validate(state, work)
    if not isinstance(state, dict):
        return errors
    if "research_contract" in state and state["research_contract"] != "1":
        errors.append("unsupported research_contract; retain the original state")
    if "value_contract" in state and (state["value_contract"] != "1" or state.get("research_contract") != "1"):
        errors.append("unsupported value_contract; preserve the original records")
    if state.get("framework_version") != "0.2":
        errors.append("framework_version mismatch; do not silently import old approvals")
    if not isinstance(state.get("nodes"), list) or any(not isinstance(n, dict) for n in state["nodes"]):
        return errors
    extensions = state.get("extensions")
    if (not isinstance(extensions, dict) or not isinstance(extensions.get("bindings"), dict)
            or not isinstance(extensions.get("extra_capabilities"), dict)):
        errors.append("invalid extension records")
    for node in state["nodes"]:
        if any(k not in node for k in core.new_node("R01")):
            continue
        if node["status"] in {"awaiting_review", "approved"}:
            if not isinstance(node["artifacts"], list) or any(not isinstance(a, dict) for a in node["artifacts"]):
                continue
            roles = {row.get("role") for row in node["artifacts"]}
            missing = set(required_outputs(state, node["round"])) - roles
            if missing:
                errors.append(node["id"] + ": missing output roles " + ", ".join(sorted(missing)))
            try:
                choice_schema(node["choices"], node["round"], state)
                options = research_delivery(state, work, node["round"], node["artifacts"])
                if node["round"] == "R02" and state.get("value_contract") == "1":
                    value_choices(node["choices"], work, node["artifacts"])
                if options is not None:
                    chosen = next(c for c in node["choices"] if c["id"] == "mainline")
                    if {o["id"] for o in chosen["options"]} != options:
                        raise WorkflowError("mainline choice IDs differ from checked options")
            except (WorkflowError, OSError, ValueError, KeyError, TypeError) as exc:
                errors.append(node["id"] + ": " + str(exc))
        if node["round"] == "R05" and node["status"] == "approved":
            try:
                plan_path = next(core.file_path(work, a["path"]) for a in node["artifacts"] if a["role"] == "unit_plan")
                chosen = json.loads(node["decision_summary"])["architecture"]
                plan = plans_from(plan_path, node["choices"])[chosen]
                if state["units"] != plan["units"] or state["order"] != plan["order"]:
                    errors.append("R05: units/order differ from the approved architecture; reopen R05")
            except (WorkflowError, OSError, KeyError, TypeError, ValueError, StopIteration) as exc:
                errors.append("R05: invalid approved architecture record: " + str(exc))
    return errors


def doctor(work=None):
    errors = [CONFIG_ERROR] if CONFIG_ERROR else []
    if sys.version_info < (3, 9):
        errors.append("Python 3.9 or newer is required; use the intended environment's interpreter")
    workflow = {"initialized": False}
    if work is not None:
        target = work / "workflow-state.json"
        workflow["directory"] = str(work)
        if target.exists():
            try:
                state = load(target)
                errors.extend(checks(state, work))
                workflow.update(initialized=True, lock_present=(work / ".workflow.lock").exists())
                if not errors:
                    workflow["next"] = route(state, work)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append("state unreadable: " + str(exc))
        else:
            workflow["next"] = "init this directory with an existing --project-root"
    return {"ok": not errors, "python": {"version": platform.python_version(),
            "implementation": platform.python_implementation(), "executable": sys.executable,
            "prefix": sys.prefix, "base_prefix": sys.base_prefix,
            "in_virtualenv": sys.prefix != sys.base_prefix,
            "minimum": "3.9", "platform": sys.platform}, "dependencies": "Python standard library only",
            "workflow": workflow, "errors": errors,
            "note": "Read-only diagnosis. Never delete a lock until its owner has stopped; keep the original state when restoring a backup."}


def ensure(state, work):
    errors = checks(state, work)
    if errors:
        raise WorkflowError("; ".join(errors))


def route(state, work):
    errors = checks(state, work)
    if errors:
        return {"record_check": "FAIL", "errors": errors, "action": "reopen affected nodes; never refresh old approval hashes"}
    nid = next_id(state)
    if nid is None:
        return {"record_check": "PASS", "mode": state["mode"], "current": None,
                "action": "planning_complete_stop" if state["mode"] == "plan_only" else "manuscript_review_complete_no_submission"}
    node = get_node(state, nid)
    if node["round"] in {"R04", "R05", "R06", "R07", "R08"} and author_focus(state, work) is None:
        return {"record_check": "PASS", "current": nid, "action": "needs_author_value_focus",
                "instruction": "reopen R02 --adopt-value-focus, deliver value analysis and obtain explicit author selection; very old research contracts need a new work directory"}
    action = "work_current_node"
    if node["status"] == "awaiting_review":
        action = "wait_for_human_review"
    elif nid.startswith("R07:") and node["unit"] not in (state.get("writing_authority") or {}):
        action = "needs_explicit_unit_writing_authority"
    return {"record_check": "PASS", "mode": state["mode"], "current": nid,
            "status": node["status"], "action": action,
            "open_items": node["open_items"], "blocking_issues": node["blocking_issues"]}


def skill_roots(extra=()):
    paths = [Path(p).expanduser().resolve() for p in extra]
    codex = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    paths += [codex / "skills", Path.home() / ".agents/skills"]
    paths += sorted((codex / "plugins/cache").glob("*/*/*/skills"), reverse=True)
    return list(dict.fromkeys(paths))


def discover(capability, extra=()):
    config = CAPS.get(capability, {"candidates": [], "description": "custom capability"})
    found = []
    roots = skill_roots(extra)
    for name in config.get("candidates", []):
        entries = [root / name / "SKILL.md" for root in roots
                   if (root / name / "SKILL.md").is_file()]
        entry = entries[0] if entries else None
        found.append({"name": name, "available": entry is not None,
                      "entry": str(entry) if entry else None,
                      "entries": [str(p) for p in entries],
                      "discovery_status": "found" if entry else "not_found_in_searched_roots",
                      "bytes": entry.stat().st_size if entry else None})
    return {"capability": capability, "description": config.get("description", ""), "candidates": found,
            "searched_roots": [str(p) for p in roots],
            "note": "installed copies, not a claim about which version the host has activated"}


def active_caps(state, stage):
    return list(dict.fromkeys(STAGES[stage]["capabilities"] +
                state["extensions"]["extra_capabilities"].get(stage, [])))


def provider(state, capability):
    binding = state["extensions"]["bindings"].get(capability)
    if not binding:
        return {"capability": capability, "binding": None,
                "instruction": "use available tools directly, or discover and bind one provider; no automatic installation"}
    entry = Path(binding["entry"])
    available = entry.is_file()
    if binding["required"] and not available:
        raise WorkflowError("required skill unavailable: " + capability)
    return {"capability": capability, **binding, "available": available,
            "changed_since_binding": available and core.digest(entry) != binding["sha256"],
            "entry_chars": len(entry.read_text(encoding="utf-8")) if available else None,
            "instruction": ("read this provider only when needed; return current-task outputs, never approve or run another pipeline"
                            if available else "optional provider unavailable; use available tools directly for this task")}


def providers_for(state, node):
    if node["status"] == "working" and node["provider_context"]:
        rows = node["provider_context"]
        for row in rows:
            if row.get("entry"):
                if row.get("available") is False and not row.get("required"):
                    # Absence was frozen at start; a later installation is not activated.
                    continue
                entry = Path(row["entry"])
                if not entry.is_file() or core.digest(entry) != row["sha256"]:
                    raise WorkflowError("provider changed during task; reopen this node and rebind before restarting")
        return copy.deepcopy(rows)
    return [provider(state, c) for c in active_caps(state, node["round"])]


def delivery_refs(node):
    return [{"role": a["role"], "path": a["path"]}
            for a in node.get("artifacts", []) if a["role"] != "result_record"]


def revision_context(node):
    latest = next((h for h in reversed(node["history"])
                   if h.get("event") in {"revision_requested", "reopened"}), None)
    if latest is None:
        return None
    previous = latest["previous"]
    return {"event": latest["event"], "request": latest.get("user_quote", latest.get("reason")),
            "message_ref": latest.get("message_ref"),
            "previous_delivery": {"status": previous["status"],
                                  "summary": previous["result_summary"],
                                  "artifact_refs": delivery_refs(previous)}}


def related_texts(state, node):
    if node["round"] not in {"R07", "R08"}:
        return []
    units = state["units"]
    if node["round"] == "R07":
        position = next(i for i, u in enumerate(units) if u["id"] == node["unit"])
        units = [u for i, u in enumerate(units) if abs(i - position) == 1]
    by_id = nodes(state)
    return [{"node": n["id"], "title": u["title"], "artifact_refs": delivery_refs(n),
             "input_refs": copy.deepcopy(n["inputs"])}
            for u in units for n in [by_id.get("R07:" + u["id"], {})]
            if n.get("status") == "approved"]


def packet(state, work, max_chars=8000, request=None):
    status = route(state, work)
    if status["record_check"] != "PASS":
        raise WorkflowError("; ".join(status["errors"]))
    if status.get("current") is None or status["action"] != "work_current_node":
        return status
    node = get_node(state, status["current"])
    stage = node["round"]
    contract = copy.deepcopy(STAGES[stage])
    contract["outputs"] = required_outputs(state, stage)
    if stage in {"R02", "R04"}:
        contract["research_records"] = "Read references/research-records.md only for this task; use scripts/research_map.py. New workflows require versioned source/claim/relationship records; existing workflows keep their recorded contract."
    inherited = []
    refs = contract.pop("inherit")
    capabilities = active_caps(state, stage)
    if request:
        if not isinstance(request["goal"], str) or not 1 <= len(request["goal"].strip()) <= 1000:
            raise WorkflowError("capability request needs a nonempty goal of at most 1000 characters")
        if node["status"] != "working" or request["capability"] not in capabilities:
            raise WorkflowError("capability request needs a current working task and an active capability")
        if request["role"] not in contract["outputs"] + ["supporting_note"]:
            raise WorkflowError("request output role must belong to this stage or be supporting_note")
        ids = {m["id"] for m in node["context_materials"]}
        if set(request["materials"]) - ids:
            raise WorkflowError("request references unknown material IDs")
        core.file_path(work, request["output"])
        contract = {"title": contract["title"] + ": bounded capability request",
                    "objective": request["goal"], "output_role": request["role"],
                    "output_path": request["output"],
                    "limits": "Only selected materials and requested output. Return evidence/unknowns; no approval or next-stage authority."}
    for ref in refs:
        if ref == "matching_plan":
            ref = "R06:" + node["unit"]
        n = nodes(state).get(ref)
        if n and n["status"] == "approved":
            inherited.append({"node": ref, "summary": n["result_summary"],
                              "human_decisions": n["decision_summary"],
                              "artifact_refs": delivery_refs(n)})
    focus = author_focus(state, work)
    result = {"node": node["id"], "unit": next((u for u in state["units"] if u["id"] == node["unit"]), None),
              "work_directory": str(work), "project_root": state["project_root"],
              "mode": state["mode"], "task": contract, "approved_context": inherited,
              "capabilities": [p for p in providers_for(state, node)
                               if not request or p["capability"] == request["capability"]],
              "materials": [], "omitted_optional_materials": [],
              "boundary": ("return the requested artifact to the main workflow; it assembles the complete stage delivery for author review"
                           if request else "complete this task, submit concrete artifacts, then wait for human review"),
              "budget_chars": max_chars, "chars": 0}
    if focus:
        result["author_focus"] = focus
    revision = revision_context(node)
    if revision:
        result["revision_context"] = revision
    related = related_texts(state, node)
    if related:
        result["related_texts"] = related
    if stage == "R07":
        result["writing_authority"] = state["writing_authority"][node["unit"]]
    optional = []
    for material in node["context_materials"]:
        if request and material["id"] not in request["materials"]:
            continue
        item = copy.deepcopy(material)
        path = core.file_path(state["project_root"], item["path"])
        if core.digest(path) != item["sha256"]:
            raise WorkflowError("material changed; reopen/refresh explicitly: " + item["id"])
        if item.get("start") is not None:
            item["content"] = core.excerpt(path, item["start"], item["end"])
        (result["materials"] if item["required"] else optional).append(item)
    def size():
        for _ in range(8):
            length = len(json.dumps(result, ensure_ascii=False, indent=2))
            if length == result["chars"]:
                return length
            result["chars"] = length
        return len(json.dumps(result, ensure_ascii=False, indent=2))
    for item in optional:
        result["materials"].append(item)
        if size() > max_chars:
            result["materials"].pop()
            result["omitted_optional_materials"].append({"id": item["id"], "reason": "budget; not loaded"})
    if size() > max_chars:
        raise WorkflowError("required packet exceeds budget; re-attach the same material-id with fewer lines, detach its excerpt, or explicitly change --max-chars. Base-contract overflow requires a revised task/summary; automatic splitting is not implemented. No truncation")
    return result


def form(state, work):
    ensure(state, work)
    nid = next_id(state)
    if not nid:
        return route(state, work)
    stage = get_node(state, nid)["round"]
    return {"node": nid, "summary": None,
            "artifacts": [{"role": role, "path": None}
                          for role in required_outputs(state, stage)],
            "choices": [{"id": key, "prompt": None, "options": [], **({"multiple": True} if key == "value_focus" else {})}
                        for key in decision_keys(state, stage)],
            "self_check": {"performed": False, "summary": "record actual checks before submission"},
            "blocking_issues": [], "open_items": []}


def select(choices, given):
    result = {}
    if not isinstance(given, dict):
        raise WorkflowError("selection-file must contain a decision-to-option object")
    if set(given) - {c["id"] for c in choices}:
        raise WorkflowError("selection contains unknown decision keys")
    for choice in choices:
        valid = {o["id"] for o in choice["options"]}
        if choice["id"] == "value_focus":
            focus = given.get("value_focus")
            selected = focus.get("selected") if isinstance(focus, dict) else None
            reason = focus.get("reason") if isinstance(focus, dict) else None
            if (not isinstance(selected, list) or not selected or any(not isinstance(i, str) for i in selected)
                    or len(selected) != len(set(selected)) or set(selected) - valid
                    or (reason is not None and (not core.nonempty(reason) or len(reason) > 600))):
                raise WorkflowError("explicit author value_focus selection required, including for one recommended option")
            result["value_focus"] = {"selected": selected, "reason": reason}
            continue
        value = given.get(choice["id"])
        if value is None and len(valid) == 1:
            value = next(iter(valid))
        values = value if isinstance(value, list) else [value]
        if (not values or len(values) != len(set(values)) or any(not isinstance(v, str) or v not in valid for v in values)
                or (isinstance(value, list) and not choice.get("multiple", False))):
            raise WorkflowError("explicit valid human selection required: " + choice["id"])
        result[choice["id"]] = value
    return result


def plans_from(path, choices):
    data = load(path)
    valid = {o["id"] for c in choices if c["id"] == "architecture" for o in c["options"]}
    if not isinstance(data, dict) or set(data.get("plans", {})) != valid:
        raise WorkflowError("unit_plan.plans must match architecture option IDs")
    for plan in data["plans"].values():
        if plan.get("order") not in {"all_plans_first", "section_cycle"}:
            raise WorkflowError("unit_plan needs an explicit valid processing order")
        units = plan.get("units")
        if not isinstance(units, list) or not units:
            raise WorkflowError("unit_plan needs a nonempty unit list")
        ids = [u.get("id") for u in units if isinstance(u, dict)]
        if (len(ids) != len(units) or len(ids) != len(set(ids)) or
                any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", i) for i in ids)
                or any(not u.get("title") for u in units)):
            raise WorkflowError("unit IDs/titles must be valid and unique")
    return data["plans"]


def mutate(state, work, args):
    command = args.command
    if command == "reopen":
        if args.adopt_value_focus and (args.node != "R02" or state.get("research_contract") != "1"):
            raise WorkflowError("adopt value focus at R02 with research_contract 1; otherwise start a new work directory")
        if not core.nonempty(args.reason):
            raise WorkflowError("reopening a task needs an explicit reason")
        by_id = nodes(state)
        if args.node not in by_id:
            raise WorkflowError("unknown node")
        affected = {args.node}
        while True:
            updated = affected | {n["id"] for n in state["nodes"] if set(n["depends_on"]) & affected}
            if updated == affected:
                break
            affected = updated
        for nid in affected:
            n = by_id[nid]
            n["history"].append({"event": "reopened", "reason": args.reason,
                                  "previous": {k: copy.deepcopy(v) for k, v in n.items() if k != "history"}})
            n.update(status="stale", approval=None, decision_summary="")
        if "R05" in affected:
            retired = [n for n in state["nodes"] if n["round"] in {"R07", "R08"}]
            state.setdefault("retired_nodes", []).extend(copy.deepcopy(retired))
            state["nodes"] = [n for n in state["nodes"] if n["round"] not in {"R07", "R08"}]
            if state.get("writing_authority"):
                event(state, "writing_authority_revoked", args.node,
                      authority=copy.deepcopy(state["writing_authority"]), reason=args.reason)
            state["mode"], state["writing_authority"] = "plan_only", None
        if args.adopt_value_focus:
            state["value_contract"] = "1"
        event(state, "reopen", args.node, affected=sorted(affected), reason=args.reason)
        return {"reopened": sorted(affected)}
    ensure(state, work)
    if command in {"review", "authorize"} and any(not core.nonempty(v) for v in [args.message_ref, args.quote]):
        raise WorkflowError("human review/authority needs a nonblank message reference and quotation")
    if command == "bind":
        if any(n["status"] in {"working", "awaiting_review"} for n in state["nodes"]):
            raise WorkflowError("finish revision/reopen the current task before changing its provider; old approved results keep their frozen provenance")
        entry = Path(args.entry).expanduser().resolve()
        if not entry.is_file():
            raise WorkflowError("skill entry is not installed/readable")
        if args.capability not in CAPS and not args.stage:
            raise WorkflowError("custom capability needs --stage to specify where it applies")
        state["extensions"]["bindings"][args.capability] = {
            "entry": str(entry), "sha256": core.digest(entry), "hint": args.hint,
            "required": args.required}
        if args.stage:
            extras = state["extensions"]["extra_capabilities"].setdefault(args.stage, [])
            if args.capability not in extras:
                extras.append(args.capability)
        event(state, "bind", capability=args.capability)
        return {"bound": args.capability, "entry": str(entry), "executed": False}
    if command == "authorize":
        if author_focus(state, work) is None:
            raise WorkflowError("author value focus must be confirmed before writing authorization")
        if not args.message_ref.strip() or not args.quote.strip():
            raise WorkflowError("writing authority requires a real message reference and quotation")
        if nodes(state)["R05"]["status"] != "approved" or args.unit not in {u["id"] for u in state["units"]}:
            raise WorkflowError("writing authority needs an approved architecture and declared unit")
        if any(n["status"] == "awaiting_review" for n in state["nodes"]):
            raise WorkflowError("finish current human review before changing execution mode")
        state["mode"] = "guided_writing"
        if state["writing_authority"] is None:
            state["writing_authority"] = {}
        state["writing_authority"][args.unit] = {"message_ref": args.message_ref, "user_quote": args.quote,
                                                "scope": args.unit, "method": args.method}
        get_node(state, "R07:" + args.unit, create=True)
        event(state, "writing_authority", "R07:" + args.unit, message_ref=args.message_ref)
        return {"authorized_unit": args.unit, "method": args.method, "automatic_execution": False}
    nid = next_id(state)
    if nid is None:
        raise WorkflowError("workflow is complete for the current mode; no automatic drafting")
    if get_node(state, nid)["round"] in {"R04", "R05", "R06", "R07", "R08"} and author_focus(state, work) is None:
        raise WorkflowError("confirm author value focus before mainline planning; reopen R02 --adopt-value-focus")
    node = get_node(state, nid, create=True)
    if nid.startswith("R07:") and node["unit"] not in (state.get("writing_authority") or {}):
        raise WorkflowError("this unit needs explicit writing authority")
    if command == "start":
        if node["status"] not in {"not_started", "stale", "revision_requested"}:
            raise WorkflowError("cannot start this status: " + node["status"])
        if any(nodes(state)[d]["status"] != "approved" for d in node["depends_on"]):
            raise WorkflowError("prerequisites must be human-approved")
        if node["status"] in {"stale", "revision_requested"}:
            node["revision"] += 1
            node.update(artifacts=[], choices=[], result_summary="", blocking_issues=[], open_items=[],
                        self_check={"performed": False, "summary": ""})
            for material in node["context_materials"]:
                material["sha256"] = core.digest(core.file_path(state["project_root"], material["path"]))
            for item in node["inputs"]:
                item["sha256"] = core.digest(core.file_path(state["project_root"], item["path"]))
        current_providers = [provider(state, c) for c in active_caps(state, node["round"])]
        if any(p.get("changed_since_binding") for p in current_providers):
            raise WorkflowError("provider changed since binding; explicitly rebind before starting")
        node["provider_context"], node["packet_budget"] = current_providers, args.max_chars
        node["status"] = "working"
        task = packet(state, work, args.max_chars)
        event(state, "start", nid, packet_sha256=core.packed(task), packet_chars=task.get("chars"))
        return {"started": nid, "revision": node["revision"], "packet_chars": task.get("chars")}
    if command == "attach":
        if not core.nonempty(args.material_id):
            raise WorkflowError("material-id must be a nonblank string")
        if node["status"] not in {"not_started", "working", "revision_requested", "stale"}:
            raise WorkflowError("cannot change materials after delivery; request revision/reopen")
        root = Path(state["project_root"])
        path = Path(args.path).expanduser()
        path = path.resolve() if path.is_absolute() else (root / path).resolve()
        try:
            relative = str(path.relative_to(root.resolve()))
        except ValueError:
            raise WorkflowError("material must be within the authorized project root") from None
        if not path.is_file() or ((args.start is None) != (args.end is None)):
            raise WorkflowError("material needs a real file and paired start/end lines")
        if args.start is not None:
            if not (1 <= args.start <= args.end):
                raise WorkflowError("invalid line range")
            core.excerpt(path, args.start, args.end)
        item = {"id": args.material_id, "path": relative, "sha256": core.digest(path),
                "start": args.start, "end": args.end, "required": not args.optional, "note": args.note}
        node["context_materials"] = [m for m in node["context_materials"] if m["id"] != item["id"]] + [item]
        node["inputs"] = [i for i in node["inputs"] if i["path"] != item["path"]] + [{"path": item["path"], "sha256": item["sha256"]}]
        event(state, "attach", nid, material_id=item["id"])
        return {"attached": item["id"], "content_mode": "selected_lines" if args.start else "reference_only"}
    if command == "detach":
        if node["status"] not in {"not_started", "working", "revision_requested", "stale"}:
            raise WorkflowError("cannot change context after delivery; request revision/reopen")
        if args.material_id not in {m["id"] for m in node["context_materials"]}:
            raise WorkflowError("unknown material-id")
        node["context_materials"] = [m for m in node["context_materials"] if m["id"] != args.material_id]
        event(state, "detach_excerpt", nid, material_id=args.material_id)
        return {"detached_excerpt": args.material_id, "source_hash_retained": True}
    if command == "retire-input":
        if node["status"] not in {"not_started", "stale", "revision_requested"}:
            raise WorkflowError("reopen the affected task before retiring a registered input")
        if not core.nonempty(args.reason):
            raise WorkflowError("retiring an input needs an explicit reason")
        target = core.file_path(state["project_root"], args.path)
        rows = [i for i in node["inputs"] if core.file_path(state["project_root"], i["path"]) == target]
        if not rows:
            raise WorkflowError("input is not registered on this task; reopen its earliest affected node first")
        for row in rows:
            node["history"].append({"event": "input_retired", "reason": args.reason, "input": copy.deepcopy(row),
                                    "materials": copy.deepcopy([m for m in node["context_materials"]
                                        if core.file_path(state["project_root"], m["path"]) == target])})
        node["inputs"] = [i for i in node["inputs"] if i not in rows]
        node["context_materials"] = [m for m in node["context_materials"]
                                     if core.file_path(state["project_root"], m["path"]) != target]
        event(state, "input_retired", nid, path=args.path, reason=args.reason)
        return {"retired_input": args.path, "historical_hash_preserved": True}
    if command == "submit":
        if node["status"] != "working":
            raise WorkflowError("only the current working node can submit")
        packet(state, work, node["packet_budget"])
        if any(core.digest(core.file_path(state["project_root"], i["path"])) != i["sha256"] for i in node["inputs"]):
            raise WorkflowError("registered input changed during task; reopen before submission")
        result = load(args.result)
        if result.get("node") != nid or not core.nonempty(result.get("summary")) or len(result["summary"]) > 600:
            raise WorkflowError("result needs matching node and a 1..600 character factual summary")
        choice_schema(result.get("choices"), node["round"], state)
        check = result.get("self_check")
        if not isinstance(check, dict) or check.get("performed") is not True or not core.nonempty(check.get("summary")):
            raise WorkflowError("record actual self-check before submitting")
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, list) or any(not isinstance(a, dict) for a in artifacts):
            raise WorkflowError("artifacts must be a list")
        roles = [a.get("role") for a in artifacts]
        if len(roles) != len(set(roles)) or set(required_outputs(state, node["round"])) - set(roles):
            raise WorkflowError("missing or duplicate output roles")
        sources = [(a, core.file_path(work, a["path"])) for a in artifacts]
        if any(not p.is_file() for _, p in sources):
            raise WorkflowError("all artifacts must exist before submission")
        options = research_delivery(state, work, node["round"], artifacts)
        if node["round"] == "R02" and state.get("value_contract") == "1":
            value_choices(result["choices"], work, artifacts)
        if options is not None:
            chosen = next(c for c in result["choices"] if c["id"] == "mainline")
            if {o["id"] for o in chosen["options"]} != options:
                raise WorkflowError("mainline choice IDs differ from checked options")
        if node["round"] == "R05":
            plans_from(next(p for a, p in sources if a["role"] == "unit_plan"), result["choices"])
        for field in ["blocking_issues", "open_items"]:
            if not isinstance(result.get(field), list):
                raise WorkflowError(field + " must be a list")
        frozen = work / "receipts" / nid.replace(":", "_") / f"r{node['revision']}-{uuid.uuid4().hex[:8]}"
        frozen.mkdir(parents=True)
        rows = []
        for a, source in sources:
            if not isinstance(a["role"], str) or not re.fullmatch(r"[a-z][a-z0-9_]*", a["role"]):
                raise WorkflowError("invalid artifact role")
            destination = frozen / (a["role"] + source.suffix)
            shutil.copy2(source, destination)
            rows.append({"role": a["role"], "path": str(destination.relative_to(work)), "sha256": core.digest(destination)})
        write(frozen / "result.json", result)
        rows.append({"role": "result_record", "path": str((frozen / "result.json").relative_to(work)), "sha256": core.digest(frozen / "result.json")})
        node.update(status="awaiting_review", artifacts=rows, choices=result["choices"],
                    result_summary=result["summary"], self_check=check,
                    blocking_issues=result["blocking_issues"], open_items=result["open_items"])
        ensure(state, work)
        event(state, "submitted", nid, revision=node["revision"])
        return {"node": nid, "status": "awaiting_review", "summary": node["result_summary"],
                "artifacts": rows, "human_review": STAGES[node["round"]]["human_review"],
                "choices": node["choices"], "blocking_issues": node["blocking_issues"],
                "open_items": node["open_items"], "next": "wait_for_human_review"}
    if command == "review":
        if node["status"] != "awaiting_review":
            raise WorkflowError("human review must refer to a concrete awaiting-review delivery")
        if args.decision == "revise":
            node["history"].append({"event": "revision_requested", "message_ref": args.message_ref,
                                    "user_quote": args.quote,
                                    "previous": {k: copy.deepcopy(v) for k, v in node.items() if k != "history"}})
            node["status"] = "revision_requested"
            event(state, "revise", nid, message_ref=args.message_ref)
            return {"node": nid, "status": "revision_requested"}
        if node["blocking_issues"]:
            raise WorkflowError("resolve blockers or explicitly revise the delivery scope before approval")
        given = load(args.selection_file) if args.selection_file else {}
        chosen = select(node["choices"], given)
        if node["round"] == "R05":
            plan_path = next(work / a["path"] for a in node["artifacts"] if a["role"] == "unit_plan")
            selected = plans_from(plan_path, node["choices"])[chosen["architecture"]]
            state["units"], state["order"] = selected["units"], selected["order"]
            valid_units = {u["id"] for u in state["units"]}
            retired = [n for n in state["nodes"] if n["round"] == "R08" or
                       (n["round"] in {"R06", "R07"} and n["unit"] not in valid_units)]
            state.setdefault("retired_nodes", []).extend(copy.deepcopy(retired))
            retired_ids = {n["id"] for n in retired}
            state["nodes"] = [n for n in state["nodes"] if n["id"] not in retired_ids]
            if state["writing_authority"]:
                state["writing_authority"] = {u: a for u, a in state["writing_authority"].items() if u in valid_units}
                if not state["writing_authority"]:
                    state["mode"], state["writing_authority"] = "plan_only", None
            for unit in state["units"]:
                get_node(state, "R06:" + unit["id"], create=True)
        node["decision_summary"] = json.dumps(chosen, ensure_ascii=False, sort_keys=True)
        node["status"] = "approved"
        node["approval"] = {"actor": "user", "message_ref": args.message_ref, "user_quote": args.quote,
                             "scope": nid, "snapshot_sha256": core.snapshot(state, nid)}
        event(state, "approved", nid, message_ref=args.message_ref, selection=chosen)
        ensure(state, work)
        return {"approved": nid, "selection": chosen, "next": route(state, work),
                "note": "Record consistency only; actual human authorization must exist."}
    raise WorkflowError("unknown mutation")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ["init", "doctor", "status", "packet", "request", "start", "form", "attach", "detach", "retire-input", "submit", "review", "reopen", "authorize", "bind", "discover", "help"]:
        s = sub.add_parser(name)
        s.add_argument("work", type=Path, nargs="?" if name in {"help", "doctor"} else None)
        if name == "init":
            s.add_argument("--project-root", type=Path, default=Path.cwd())
        if name in {"packet", "start", "request"}:
            s.add_argument("--max-chars", type=int, default=8000)
        if name == "request":
            s.add_argument("--capability", required=True)
            s.add_argument("--goal", required=True)
            s.add_argument("--material-id", action="append", default=[])
            s.add_argument("--output-role", required=True)
            s.add_argument("--output", required=True)
        if name == "attach":
            s.add_argument("--path", required=True)
            s.add_argument("--material-id", required=True)
            s.add_argument("--start", type=int)
            s.add_argument("--end", type=int)
            s.add_argument("--optional", action="store_true")
            s.add_argument("--note", default="")
        if name == "detach":
            s.add_argument("--material-id", required=True)
        if name == "retire-input":
            s.add_argument("--path", required=True)
            s.add_argument("--reason", required=True)
        if name == "submit":
            s.add_argument("--result", type=Path, required=True)
        if name in {"review", "authorize"}:
            s.add_argument("--message-ref", required=True)
            s.add_argument("--quote", required=True)
        if name == "review":
            s.add_argument("--decision", choices=["approve", "revise"], required=True)
            s.add_argument("--selection-file", type=Path)
        if name == "reopen":
            s.add_argument("--node", required=True)
            s.add_argument("--reason", required=True)
            s.add_argument("--adopt-value-focus", action="store_true")
        if name == "authorize":
            s.add_argument("--unit", required=True)
            s.add_argument("--method", choices=["author_drafts", "expression_support", "bounded_ai_draft"], required=True)
        if name == "bind":
            s.add_argument("--capability", required=True)
            s.add_argument("--entry", required=True)
            s.add_argument("--hint", default="only the current task; no full pipeline or approval authority")
            s.add_argument("--stage", choices=[r for r in STAGES if re.fullmatch(r"R\d\d", r)])
            s.add_argument("--required", action="store_true")
        if name == "discover":
            s.add_argument("--capability")
            s.add_argument("--root", action="append", default=[])
    return p


def main():
    core.configure_stdio()
    args = parser().parse_args()
    try:
        if sys.version_info < (3, 9) and args.command != "doctor":
            raise WorkflowError("Python 3.9 or newer is required; run doctor with the intended interpreter")
        if args.command == "doctor":
            result = doctor(args.work.expanduser().resolve() if args.work else None)
        elif args.command == "help":
            result = {"commands": ["init", "doctor", "status", "packet", "request", "start", "form", "attach", "detach", "retire-input", "submit", "review", "reopen", "authorize", "bind", "discover"],
                      "result_contract": "form emits the current result schema; artifacts are work-relative; inputs are project-relative",
                      "review": "approve only after a real human message; ambiguous choices and R02 value_focus (even one option) need selection-file; preserve supplied reason",
                      "value_focus": "R02 explicit author selection precedes mainlines; author_focus carries selected content/reason/version to later packets and requests; old workdirs reopen R02 --adopt-value-focus",
                      "packet_recovery": "same-ID attach with fewer lines; detach excerpt while retaining source hash; retire-input --path OLD --reason TEXT after reopening to explicitly retire a moved/deleted input, then attach its replacement. No automatic task splitting.",
                      "architecture_changes": "reopening R05 or an earlier dependency retires writing nodes and revokes old unit writing authority; authorize again after the new architecture is approved",
                      "provider_versions": "bind before task; start freezes entry hashes; mid-task changes require reopen/rebind; prior approved outputs retain provenance",
                      "capability_request": "request --capability CAP --goal TEXT --material-id ID --output-role supporting_note --output notes/result.json; emits a small handoff, never executes a model/skill or approves",
                      "unit_plan": {"plans": {"architecture_option_id": {"units": [{"id": "intro", "title": "Introduction"}], "order": "all_plans_first"}}},
                      "limits": "record validation is not human authentication or scientific validation; packet budget cannot clear host context"}
        else:
            if CONFIG_ERROR:
                raise WorkflowError(CONFIG_ERROR)
            work = args.work.expanduser().resolve()
            if args.command == "init":
                result = init(work, args.project_root.expanduser().resolve())
            elif args.command in MUTATIONS:
                with locked(work):
                    state = load(work / "workflow-state.json")
                    result = mutate(state, work, args)
                    if args.command != "reopen":
                        ensure(state, work)
                    write(work / "workflow-state.json", state)
            else:
                state = load(work / "workflow-state.json")
                if args.command == "status":
                    result = route(state, work)
                elif args.command == "packet":
                    result = packet(state, work, args.max_chars)
                elif args.command == "request":
                    result = packet(state, work, args.max_chars, request={
                        "capability": args.capability, "goal": args.goal, "materials": args.material_id,
                        "role": args.output_role, "output": args.output})
                elif args.command == "form":
                    result = form(state, work)
                elif args.command == "discover":
                    ensure(state, work)
                    nid = next_id(state)
                    capabilities = [args.capability] if args.capability else (
                        active_caps(state, get_node(state, nid)["round"]) if nid else [])
                    result = {"capabilities": [discover(c, args.root) for c in capabilities], "executed": False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("record_check") == "FAIL" or result.get("ok") is False else 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError, StopIteration) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
