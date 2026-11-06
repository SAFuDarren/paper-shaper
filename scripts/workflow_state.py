#!/usr/bin/env python3
"""Read-only workflow checks, except non-overwriting initialization. Standard library only."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


STATES = {"not_started", "working", "awaiting_input", "awaiting_review",
          "revision_requested", "approved", "stale"}
ACTIVE = {"working", "awaiting_input", "awaiting_review", "revision_requested"}
READY = {"awaiting_review", "approved"}
REQUIRED = [f"R{i:02d}" for i in range(1, 6)]


def configure_stdio():
    """The CLI's JSON protocol is UTF-8 even when Windows redirects its streams."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def packed(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_node(round_id, unit=None):
    node_id = f"{round_id}:{unit}" if unit else round_id
    number = int(round_id[1:])
    deps = [] if number == 1 else [f"R{number - 1:02d}"]
    if number == 6:
        deps = ["R05"]
    if number == 7:
        deps = [f"R06:{unit}"]
    if number == 8:
        deps = []  # Fill from the actual approved unit list.
    return {"id": node_id, "round": round_id, "unit": unit, "revision": 1,
            "status": "not_started", "depends_on": deps, "inputs": [],
            "artifacts": [], "self_check": {"performed": False, "summary": ""},
            "blocking_issues": [], "open_items": [], "decision_summary": "",
            "approval": None, "history": [], "choices": [], "result_summary": "",
            "context_materials": [], "provider_context": [], "packet_budget": 8000}


def initial_state(project_root):
    return {"schema_version": "1.0", "workflow_version": "0.2",
            "project_root": str(Path(project_root).resolve()), "mode": "plan_only",
            "writing_authority": None, "units": [],
            "nodes": [new_node(r) for r in REQUIRED]}


def snapshot(state, node_id, stack=None):
    stack = [] if stack is None else stack
    if node_id in stack:
        raise ValueError("dependency cycle: " + " -> ".join(stack + [node_id]))
    matches = [n for n in state["nodes"] if n["id"] == node_id]
    if len(matches) != 1:
        raise ValueError("missing or duplicate node: " + node_id)
    node = matches[0]
    keys = ["id", "round", "unit", "revision", "depends_on", "inputs", "artifacts",
            "self_check", "blocking_issues", "open_items", "decision_summary", "choices",
            "result_summary", "context_materials", "provider_context", "packet_budget"]
    payload = {k: node.get(k) for k in keys}
    payload["dependencies"] = {d: snapshot(state, d, stack + [node_id])
                               for d in node.get("depends_on", [])}
    if node["round"] == "R05":
        payload["units"] = state["units"]
    if node["round"] in {"R07", "R08"}:
        payload["mode"] = state["mode"]
    if node["round"] == "R07":
        payload["writing_authority"] = (state.get("writing_authority") or {}).get(node["unit"])
    return packed(payload)


def file_path(base, value):
    path = Path(value)
    if path.is_absolute():
        raise ValueError("state file paths must be relative to the paper work directory")
    root = Path(base).resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("state file path escapes the paper work directory") from None
    return resolved


def validate(state, base):
    errors = []
    if state.get("schema_version") != "1.0":
        errors.append("unsupported schema_version")
    if state.get("mode") not in {"plan_only", "guided_writing"}:
        errors.append("invalid mode")
    nodes = state.get("nodes")
    if not isinstance(nodes, list) or not all(isinstance(n, dict) for n in nodes):
        return errors + ["nodes must be a list of objects"]
    ids = [n.get("id") for n in nodes]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        return errors + ["node IDs must be unique nonempty strings"]
    by_id = {n["id"]: n for n in nodes}
    for r in REQUIRED:
        if r not in by_id:
            errors.append("missing required node " + r)
    units = state.get("units")
    if not isinstance(units, list) or not all(isinstance(u, dict) for u in units):
        return errors + ["units must be a list of objects"]
    unit_ids = [u.get("id") for u in units]
    if any(not isinstance(u, str) or not u for u in unit_ids) or len(unit_ids) != len(set(unit_ids)):
        errors.append("unit IDs must be unique nonempty strings")
    if any(not u.get("title") for u in units):
        errors.append("each unit needs a title")
    if state.get("mode") == "guided_writing":
        authority = state.get("writing_authority")
        if not isinstance(authority, dict) or not authority:
            errors.append("guided_writing needs explicit per-unit writing_authority records")
        else:
            for unit_id, row in authority.items():
                if (unit_id not in unit_ids or not isinstance(row, dict)
                        or any(not row.get(k) for k in ["message_ref", "user_quote", "scope"])
                        or row.get("method") not in {"author_drafts", "expression_support", "bounded_ai_draft"}):
                    errors.append("invalid per-unit writing authority: " + unit_id)
    if sum(n.get("status") in ACTIVE for n in nodes) > 1:
        errors.append("more than one active or awaiting-review unit")
    fields = set(new_node("R01"))
    for node in nodes:
        nid = node["id"]
        prefix = nid + ": "
        if fields - node.keys():
            errors.append(prefix + "missing fields: " + ", ".join(sorted(fields - node.keys())))
            continue
        r = node["round"]
        if r not in {f"R{i:02d}" for i in range(1, 9)}:
            errors.append(prefix + "invalid round")
            continue
        if node["status"] not in STATES:
            errors.append(prefix + "invalid status")
        if type(node["revision"]) is not int or node["revision"] < 1:
            errors.append(prefix + "revision must be a positive integer")
        if not isinstance(node["depends_on"], list) or any(not isinstance(d, str) for d in node["depends_on"]):
            errors.append(prefix + "depends_on must be a list of node IDs")
            continue
        unit = node["unit"]
        expected_id = f"{r}:{unit}" if r in {"R06", "R07"} else r
        if nid != expected_id or (r in {"R06", "R07"} and unit not in unit_ids):
            errors.append(prefix + "round/unit ID mismatch or undeclared unit")
        required_deps = []
        if r in REQUIRED[1:]:
            required_deps = [f"R{int(r[1:]) - 1:02d}"]
        elif r == "R06":
            required_deps = ["R05"]
        elif r == "R07":
            required_deps = [f"R06:{unit}"]
        elif r == "R08":
            required_deps = [f"R07:{u}" for u in unit_ids]
            if not unit_ids:
                errors.append(prefix + "final review needs a nonempty unit list")
        for dep in required_deps:
            if dep not in node["depends_on"]:
                errors.append(prefix + "missing prerequisite " + dep)
        if r in {"R07", "R08"} and state.get("mode") != "guided_writing":
            errors.append(prefix + "writing/final review forbidden in plan_only")
        if r == "R07" and (not isinstance(state.get("writing_authority"), dict)
                            or unit not in state["writing_authority"]):
            errors.append(prefix + "this unit has no writing authority")
        if r == "R05" and node["status"] == "approved" and not unit_ids:
            errors.append(prefix + "architecture review needs the proposed unit list")
        for dep in node["depends_on"]:
            if dep not in by_id:
                errors.append(prefix + "unknown dependency " + dep)
            elif node["status"] in ACTIVE | {"approved"} and by_id[dep]["status"] != "approved":
                errors.append(prefix + "prerequisite not approved: " + dep)
        if node["status"] in READY:
            check = node["self_check"]
            if not isinstance(check, dict) or check.get("performed") is not True or not check.get("summary"):
                errors.append(prefix + "actual self-check record required before review")
            if not node["artifacts"]:
                errors.append(prefix + "review needs a concrete artifact")
            for kind in ["inputs", "artifacts"]:
                rows = node[kind]
                if not isinstance(rows, list):
                    errors.append(prefix + kind + " must be a list")
                    continue
                for row in rows:
                    try:
                        root = Path(state.get("project_root", base)) if kind == "inputs" else base
                        path = file_path(root, row["path"])
                        if not path.is_file() or digest(path) != row["sha256"]:
                            errors.append(prefix + "missing/changed " + kind + ": " + row["path"])
                    except (OSError, KeyError, TypeError, ValueError) as exc:
                        errors.append(prefix + "invalid " + kind + " row: " + str(exc))
        if node["status"] == "approved":
            if node["blocking_issues"]:
                errors.append(prefix + "unresolved blockers cannot be approved")
            if not node["decision_summary"]:
                errors.append(prefix + "human decision summary required")
            approval = node["approval"]
            if not isinstance(approval, dict) or approval.get("actor") != "user" or any(
                    not approval.get(k) for k in ["message_ref", "user_quote", "scope", "snapshot_sha256"]):
                errors.append(prefix + "explicit human approval record required")
            else:
                try:
                    if approval["snapshot_sha256"] != snapshot(state, nid):
                        errors.append(prefix + "approval snapshot changed; re-review required")
                except (KeyError, TypeError, ValueError, RecursionError) as exc:
                    errors.append(prefix + str(exc))
        elif node["approval"] is not None:
            errors.append(prefix + "non-approved node must move previous approval to history")
        try:
            snapshot(state, nid)
        except (KeyError, TypeError, ValueError, RecursionError) as exc:
            errors.append(prefix + "invalid dependency snapshot: " + str(exc))
    return errors


def report(state, base):
    errors = validate(state, base)
    if errors:
        return {"record_check": "FAIL", "errors": errors, "action": "resolve records or stale inputs before advancing"}
    pending = next((n for n in state["nodes"] if n["status"] != "approved"), None)
    result = {"record_check": "PASS", "mode": state["mode"], "current": None,
              "note": "Record consistency only; not authentication or scientific validation."}
    if pending:
        result["current"] = {k: pending[k] for k in ["id", "status", "open_items", "blocking_issues"]}
        result["action"] = "wait for human review" if pending["status"] == "awaiting_review" else "work only on this node or resolve its prerequisites"
    else:
        by_id = {n["id"]: n for n in state["nodes"]}
        missing = [f"R06:{u['id']}" for u in state["units"] if f"R06:{u['id']}" not in by_id]
        if missing:
            result["action"] = "add next planned section node: " + missing[0]
        elif state["mode"] == "plan_only" and state["units"]:
            result["action"] = "planning complete; stop without drafting"
        elif state["mode"] == "guided_writing":
            missing = [f"R07:{u['id']}" for u in state["units"] if f"R07:{u['id']}" not in by_id]
            result["action"] = "add next authorized writing node: " + missing[0] if missing else (
                "add final review R08" if "R08" not in by_id else "human-approved manuscript review complete; no submission implied")
        else:
            result["action"] = "declare human-reviewed unit list at R05"
    return result


def main():
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init")
    p.add_argument("directory", type=Path)
    p.add_argument("--project-root", type=Path)
    for name in ["status", "validate", "snapshot"]:
        p = sub.add_parser(name)
        p.add_argument("state", type=Path)
        if name == "snapshot":
            p.add_argument("node_id")
    p = sub.add_parser("digest")
    p.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init":
            args.directory.mkdir(parents=True, exist_ok=True)
            path = args.directory / "workflow-state.json"
            value = initial_state(args.project_root or Path.cwd())
            with path.open("x", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            print(json.dumps({"created": str(path.resolve()), "mode": "plan_only"}, ensure_ascii=False))
            return 0
        if args.command == "digest":
            print(digest(args.file))
            return 0
        state = json.loads(args.state.read_text(encoding="utf-8"))
        if args.command == "snapshot":
            print(snapshot(state, args.node_id))
            return 0
        result = report(state, args.state.parent)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["record_check"] == "PASS" else 1
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
