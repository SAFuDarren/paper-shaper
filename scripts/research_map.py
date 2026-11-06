#!/usr/bin/env python3
"""Index bounded project sources and check evidence/argument records; no model calls."""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import re
import sys

import workflow_state as core

VERSION = "1"
TEXT = {".md", ".txt", ".tex", ".bib", ".py", ".r", ".json", ".csv", ".yml", ".yaml"}
SKIP = {".git", ".aws", ".ssh", ".venv", "venv", "__pycache__", "node_modules", "build"}
STATUSES = {"proved", "conditional", "finite_check", "numerical", "reported", "unverified", "open", "refuted"}
RELATIONS = {"derives", "supports", "implements", "checks", "limits", "motivates", "compares"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    # Share the controller's atomic writer without importing it at module startup.
    from framework import write
    write(path, value)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def index(root, scopes, patterns=(), follow_tex=False):
    root = Path(root).resolve()
    require(root.is_dir() and scopes, "existing root and explicit scopes are required")
    regexes = [re.compile(p) for p in patterns]
    tex_roots = [core.file_path(root, s).parent for s in scopes if Path(s).suffix.lower() == ".tex"]
    pending, files, candidates, excluded, missing, citations = deque(), {}, {}, {}, [], []
    id_families = {}
    for scope in scopes:
        path = core.file_path(root, scope)
        require(path.exists(), "scope missing: " + scope)
        pending.extend(sorted(path.rglob("*")) if path.is_dir() else [path])
    while pending:
        path = pending.popleft()
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        # Resolve symlinks, too: neither explicit scope nor TeX includes may escape root.
        path = core.file_path(root, relative)
        if relative in files or relative in excluded:
            continue
        if set(Path(relative).parts) & SKIP:
            excluded[relative] = "generated/dependency/private directory; not read"
            continue
        if path.suffix.lower() not in TEXT:
            excluded[relative] = "unsupported/binary; inspect with an appropriate reader if relevant"
            continue
        if path.stat().st_size > 8 * 1024 * 1024:
            excluded[relative] = "text exceeds 8 MiB index bound; select smaller source/export or inspect separately"
            continue
        text = path.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        files[relative] = {"path": relative, "sha256": core.digest(path),
                           "bytes": path.stat().st_size, "lines": len(lines)}
        def candidate(kind, key, line, title):
            identity = relative + "|" + kind + "|" + key
            cid = hashlib.sha256(identity.encode()).hexdigest()[:16]
            candidates.setdefault(cid, {"id": cid, "path": relative, "kind": kind,
                                        "key": key, "line": line, "title": title})
        # These are candidate locators, not a semantic or complete LaTeX parser.
        if path.suffix.lower() == ".tex":
            clean = "\n".join(re.split(r"(?<!\\)%", line, maxsplit=1)[0] for line in lines)
            for m in re.finditer(r"\\begin\{(theorem|proposition|lemma|corollary|definition)\}(?:\[([^\]]*)\])?", clean):
                stop = clean.find("\\end{" + m[1] + "}", m.end())
                body = clean[m.end():stop if stop >= 0 else m.end()]
                label = re.search(r"\\label\{([^}]+)\}", body)
                line = clean.count("\n", 0, m.start()) + 1
                candidate(m[1], label[1] if label else m[1] + "@" + str(line), line, m[2] or "")
            for m in re.finditer(r"\\cite\w*\*?(?:\[[^\]]*\])*\{([^}]+)\}", clean):
                citations.extend({"path": relative, "line": clean.count("\n", 0, m.start()) + 1,
                                  "key": key.strip()} for key in m[1].split(","))
            if follow_tex:
                for m in re.finditer(r"\\(input|include|bibliography)\{([^}]+)\}", clean):
                    for name in m[2].split(","):
                        suffix = ".bib" if m[1] == "bibliography" else ".tex"
                        name = name.strip()
                        if not Path(name).suffix:
                            name += suffix
                        options = [path.parent / name] + [base / name for base in tex_roots] + [root / name]
                        target = next((p for p in options if p.is_file()), None)
                        if target is None:
                            missing.append({"path": relative, "line": clean.count("\n", 0, m.start()) + 1, "target": name})
                        else:
                            pending.append(core.file_path(root, target.relative_to(root).as_posix()))
        for number, line in enumerate(lines, 1):
            for hint in re.finditer(r"\b([A-Z]{1,4})[0-9]{2,}(?:-[A-Z][A-Z0-9]*)?\b", line):
                family = id_families.setdefault(hint[1], {})
                family[hint[0]] = any(regex.fullmatch(hint[0]) for regex in regexes)
            for regex in regexes:
                for match in regex.finditer(line):
                    candidate("id", match.group(0), number, line.strip()[:240])
    bibkeys = set()
    for name in files:
        if Path(name).suffix.lower() == ".bib":
            bibkeys.update(re.findall(r"@\w+\s*\{\s*([^,\s]+)", (root / name).read_text(encoding="utf-8-sig")))
    return {"version": VERSION, "root": str(root), "scopes": list(scopes),
            "id_patterns": list(patterns), "follow_tex": follow_tex,
            "id_family_hints": [{"prefix": prefix, "unique_ids": len(ids),
                "unmatched_count": sum(not matched for matched in ids.values()),
                "unmatched_examples": sorted(k for k, matched in ids.items() if not matched)[:12]}
                for prefix, ids in sorted(id_families.items())],
            "files": sorted(files.values(), key=lambda f: f["path"]),
            "candidates": sorted(candidates.values(), key=lambda c: (c["path"], c["line"], c["id"])),
            "excluded": [{"path": p, "reason": r} for p, r in sorted(excluded.items())],
            "missing_includes": missing,
            "unresolved_citations": [c for c in citations if c["key"] not in bibkeys],
            "limits": "Bounded text/regex index only. File discovery is not reading; candidates are not verified results. Binary files, custom macros and unstated results need manual coverage review."}


def template(inventory_path):
    inv = load(inventory_path)
    return {"version": VERSION, "inventory_sha256": core.digest(inventory_path),
            "project": {k: "" for k in ["question", "object", "target", "baseline", "progress"]},
            "coverage_limits": [],
            "files": [{"path": f["path"], "disposition": "pending", "ranges": [], "reason": ""} for f in inv["files"]],
            "coverage": [{"candidate": c["id"], "disposition": "pending", "claim_ids": [], "reason": ""} for c in inv["candidates"]],
            "claims": [], "links": []}


def keyed(rows, label):
    require(isinstance(rows, list) and all(isinstance(r, dict) for r in rows), label + " must be an object list")
    require(all(nonblank(r.get("id")) for r in rows), label + " need nonblank IDs")
    require(len({r["id"] for r in rows}) == len(rows), "duplicate " + label + " ID")
    return {r["id"]: r for r in rows}


def validate(inventory, research, root=None, mainlines=None):
    """Check mechanical consistency. Never certifies reading, proof, relevance or novelty."""
    inv, data = load(inventory), load(research)
    require(isinstance(inv, dict) and isinstance(data, dict), "inventory/map must be JSON objects")
    require(inv.get("version") == data.get("version") == VERSION, "unsupported research contract version")
    require(data.get("inventory_sha256") == core.digest(inventory), "inventory hash differs; rebuild/review explicitly")
    root = Path(root or inv["root"]).resolve()
    errors, warnings = [], []
    files = {f["path"]: f for f in inv["files"]}
    require(files and len(files) == len(inv["files"]), "empty/duplicate inventory file set")
    for path, record in files.items():
        p = core.file_path(root, path)
        if not p.is_file() or core.digest(p) != record["sha256"]:
            errors.append("source missing/changed: " + path)
    require(isinstance(data.get("project"), dict), "project brief required")
    for key in ["question", "object", "target", "baseline", "progress"]:
        if not nonblank(data["project"].get(key)):
            errors.append("missing project understanding: " + key)
    require(isinstance(data.get("coverage_limits"), list) and data["coverage_limits"]
            and all(nonblank(s) for s in data["coverage_limits"]), "explicit coverage_limits required")
    dispositions = {}
    require(isinstance(data.get("files"), list), "file reading/disposition records required")
    for row in data["files"]:
        name = row["path"]
        require(name in files and name not in dispositions, "unknown/duplicate file disposition: " + name)
        dispositions[name] = row
        if row.get("disposition") not in {"read", "excluded", "pending"} or not nonblank(row.get("reason")):
            errors.append("file disposition/reason required: " + name)
        if row.get("disposition") == "pending":
            errors.append("file pending: " + name)
        ranges = row.get("ranges")
        require(isinstance(ranges, list), "ranges must be a list: " + name)
        for pair in ranges:
            require(isinstance(pair, list) and len(pair) == 2 and all(type(n) is int for n in pair)
                    and 1 <= pair[0] <= pair[1] <= files[name]["lines"], "invalid reading range: " + name)
        if row.get("disposition") == "read" and not ranges:
            errors.append("read file needs actual selected ranges: " + name)
    errors.extend("file unaccounted: " + name for name in files.keys() - dispositions.keys())
    def refs(rows, owner):
        require(isinstance(rows, list), owner + ": sources must be a list")
        for ref in rows:
            require(isinstance(ref, dict), owner + ": malformed source")
            name, start, end = ref.get("path"), ref.get("start"), ref.get("end")
            if name not in files:
                errors.append(owner + ": unindexed source " + str(name)); continue
            if not (type(start) is int and type(end) is int and 1 <= start <= end <= files[name]["lines"]):
                errors.append(owner + ": invalid source lines " + name); continue
            if ref.get("check") not in {"read", "reproduced", "not_checked"} or not nonblank(ref.get("role")):
                errors.append(owner + ": source role/check required")
            if ref.get("check") == "not_checked":
                warnings.append(owner + ": unchecked source " + name)
            reading = dispositions.get(name, {})
            if ref.get("check") != "not_checked" and (reading.get("disposition") != "read" or not any(a <= start and end <= b for a, b in reading.get("ranges", []))):
                errors.append(owner + ": source outside declared reading " + name)
    claims = keyed(data.get("claims"), "claim")
    require(claims, "at least one claim/open question required")
    for cid, claim in claims.items():
        for key in ["statement", "scope", "kind"]:
            if not nonblank(claim.get(key)):
                errors.append(cid + ": missing " + key)
        if claim.get("status") not in STATUSES:
            errors.append(cid + ": invalid status")
        if not isinstance(claim.get("caveats"), list):
            errors.append(cid + ": caveats list required")
        refs(claim.get("sources"), cid)
        if not claim["sources"]:
            errors.append(cid + ": no source; state unknown with the source documenting that gap")
    candidates = {c["id"]: c for c in inv["candidates"]}
    coverage = {}
    for row in data.get("coverage", []):
        cid = row["candidate"]
        require(cid in candidates and cid not in coverage, "unknown/duplicate candidate disposition: " + cid)
        coverage[cid] = row
        require(isinstance(row.get("claim_ids"), list), "candidate claim_ids list required")
        if row.get("disposition") not in {"claim", "background", "duplicate", "out_of_scope", "unresolved"}:
            errors.append("candidate pending/invalid: " + cid)
        if not nonblank(row.get("reason")):
            errors.append("candidate needs disposition reason: " + cid)
        if row.get("disposition") in {"claim", "duplicate"} and not row["claim_ids"]:
            errors.append("candidate lacks mapped claim: " + cid)
        for target in row["claim_ids"]:
            if target not in claims:
                errors.append("candidate references missing claim: " + target)
        if row.get("disposition") == "unresolved":
            warnings.append("unresolved candidate: " + cid)
    errors.extend("candidate unaccounted: " + cid for cid in candidates.keys() - coverage.keys())
    links = keyed(data.get("links"), "link")
    graph = {c: [] for c in claims}
    for lid, link in links.items():
        require(isinstance(link.get("from"), list) and link["from"], lid + ": nonempty premises required")
        endpoints = link["from"] + [link.get("to")]
        if any(c not in claims for c in endpoints):
            errors.append(lid + ": unknown claim endpoint"); continue
        if link.get("relation") not in RELATIONS or link.get("status") not in {"supported", "conditional", "gap"}:
            errors.append(lid + ": invalid relation/status")
        if not nonblank(link.get("rationale")):
            errors.append(lid + ": inference explanation required")
        refs(link.get("sources"), lid)
        if link.get("status") != "gap" and not link["sources"]:
            errors.append(lid + ": non-gap relation needs sources")
        if link.get("status") == "gap":
            warnings.append(lid + ": reasoning gap")
        if link.get("relation") == "derives":
            for premise in link["from"]:
                graph[premise].append(link["to"])
    colors = {}
    def visit(cid):
        if colors.get(cid) == 1:
            raise ValueError("derivation cycle at " + cid)
        if colors.get(cid) == 2:
            return
        colors[cid] = 1
        for target in graph[cid]:
            visit(target)
        colors[cid] = 2
    for cid in graph:
        visit(cid)
    touched = {c for link in links.values() for c in link["from"] + [link.get("to")]}
    if len(claims) > 1:
        warnings.extend("isolated claim; explain its role or add a relation: " + c for c in claims.keys() - touched)
    if inv.get("missing_includes"):
        warnings.append("unresolved TeX includes; manually delimit coverage")
    if inv.get("unresolved_citations"):
        warnings.append("citations missing from indexed bibliography; verify reference inventory")
    if mainlines is not None:
        plans = load(mainlines)
        require(isinstance(plans, dict), "mainlines must be a JSON object")
        require(plans.get("version") == VERSION and plans.get("research_map_sha256") == core.digest(research),
                "mainlines are not bound to this research map")
        options = keyed(plans.get("options"), "mainline")
        require(options, "at least one mainline option required")
        for oid, option in options.items():
            for field in ["question", "contribution", "emphasis", "tradeoffs"]:
                if not nonblank(option.get(field)):
                    errors.append(oid + ": missing " + field)
            require(isinstance(option.get("claim_ids"), list) and isinstance(option.get("steps"), list), oid + ": claims/steps lists required")
            central = option.get("central_claim")
            if central not in claims or central not in option["claim_ids"]:
                errors.append(oid + ": central claim missing from map/option")
            refs(option.get("baseline_sources"), oid)
            if not option["baseline_sources"]:
                errors.append(oid + ": baseline sources required; record unknown comparison explicitly")
            if option.get("assertion") not in {"supported", "conditional", "proposal"}:
                errors.append(oid + ": invalid assertion status")
            selected = []
            for lid in option["steps"]:
                if lid not in links:
                    errors.append(oid + ": missing reasoning step " + lid); continue
                link = links[lid]; selected.append(link)
                if any(c not in option["claim_ids"] for c in link["from"] + [link["to"]]):
                    errors.append(oid + ": step endpoints outside option claims")
                if link["status"] in {"gap", "conditional"} and option.get("assertion") == "supported":
                    errors.append(oid + ": supported mainline contains declared reasoning gap or conditional step")
            if len(option["claim_ids"]) > 1 and not any(l["to"] == central and l["relation"] in {"derives", "supports", "checks"} for l in selected):
                errors.append(oid + ": no selected reasoning step reaches central claim with an evidence relation")
            for cid in option["claim_ids"]:
                if cid not in claims:
                    errors.append(oid + ": unknown claim " + cid)
                elif option.get("assertion") == "supported":
                    if claims[cid]["status"] in {"unverified", "open", "refuted"}:
                        errors.append(oid + ": supported mainline uses unresolved/refuted claim " + cid)
                    if not any(s.get("check") in {"read", "reproduced"} for s in claims[cid]["sources"]):
                        errors.append(oid + ": supported mainline has no inspected source for " + cid)
            if not isinstance(option.get("open_items"), list):
                errors.append(oid + ": open_items list required")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "counts": {"files": len(files), "candidates": len(candidates), "accounted_candidates": len(coverage),
                       "claims": len(claims), "links": len(links)},
            "limits": data["coverage_limits"],
            "meaning": "Record/source consistency within declared scope only; not proof of reading, complete discovery, scientific correctness or best mainline."}


def main():
    core.configure_stdio()
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("index")
    s.add_argument("--root", type=Path, required=True)
    s.add_argument("--scope", action="append", required=True)
    s.add_argument("--id-pattern", action="append", default=[])
    s.add_argument("--follow-tex", action="store_true")
    s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("template")
    s.add_argument("inventory", type=Path)
    s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("check")
    s.add_argument("inventory", type=Path)
    s.add_argument("research", type=Path)
    s.add_argument("--root", type=Path)
    s.add_argument("--mainlines", type=Path)
    s.add_argument("--out", type=Path)
    args = p.parse_args()
    try:
        if args.command == "index":
            value = index(args.root, args.scope, args.id_pattern, args.follow_tex)
            save(args.out, value)
            result = {"inventory": str(args.out), "files": len(value["files"]), "candidates": len(value["candidates"]),
                      "excluded": len(value["excluded"]), "missing_includes": value["missing_includes"],
                      "id_family_hints": value["id_family_hints"]}
        elif args.command == "template":
            value = template(args.inventory)
            save(args.out, value)
            result = {"template": str(args.out), "filled": False}
        else:
            result = validate(args.inventory, args.research, args.root, args.mainlines)
            if args.out:
                save(args.out, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("ok") is False else 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
