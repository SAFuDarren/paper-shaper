# Requirements and validation

[README](../README.md) · [中文说明](../README.zh-CN.md) · [Environment coverage](environment.md)

This framework coordinates an author's work with AI. It validates records, inputs, deliveries, choices and execution order. The author judges research value, scientific adequacy, emphasis and final expression. Passing the controller tests does not establish manuscript quality or publication readiness.

## Requirements mapped to the implementation

| Requirement | Where it is handled | Validation in this audit |
| --- | --- | --- |
| Understand the project before proposing prose | R01/R02 contracts: project, implementation, results, evidence and references | A fresh-session synthetic R02 trial produced a source-linked inventory and retained its uncertainty boundaries |
| Start from the article's purpose and publication target | R01 goal choice; R03 official requirements, dated sources and exemplar analysis | Contract inspection; the controller requires the declared output roles and a human selection, while content accuracy remains for review |
| Let the author decide contribution and mainline | R04 alternatives and evidence; explicit `mainline` selection | Multiple-option approval without a concrete selection is rejected |
| Let the author decide structure and emphasis | R05 outline, pacing and architecture-linked unit plan | The selected frozen plan is checked against the live unit list and processing order |
| Plan what each section contains and how to explain it | R06 questions, content blocks, evidence, citations, explanation depth and writing prompts | Stage-contract inspection and section-plan delivery checks; the quality of the proposed route needs author review |
| Review a concrete version before proceeding | Frozen receipt files, approval records and dependency snapshots | Missing outputs, empty forms, changed artifacts, ambiguous choices, blanks and blockers are rejected |
| Default to planning | `plan_only`, section planning, explicit stop | A complete planning run creates no writing nodes and cannot start prose automatically |
| Authorize writing by unit and mode | Per-unit `author_drafts`, `expression_support` or `bounded_ai_draft` | Both planning-first and section-cycle schedules are exercised; authorization for one unit does not permit the next |
| Revisit decisions when inputs or scope change | `reopen`, dependency invalidation and authorization revocation | Architecture changes revoke old writing authority even if a unit ID is reused; the old record is retained |
| Recover after a registered file moves | Explicit `retire-input`, history preservation and replacement attachment | Deterministic regression plus a fresh-session old/new comparison using a synthetic relocated source |
| Keep the prompt small and capabilities replaceable | Short `SKILL.md`, current-stage `packet`, scoped `request`, optional bindings | Packet size is measured; overflows do not silently truncate; unrelated material/provider bodies are excluded |
| Work in ordinary Python environments | Standard-library controller, UTF-8 protocol, `doctor` and clean-environment smoke test | 18 CI configurations; exact environments and exclusions are described separately |

## Defects found and repaired

The pre-audit version passed its original 49 tests. Additional scenarios exposed issues those tests did not cover:

1. Reusing a unit ID after changing the architecture could retain an old writing authorization. Reopening R05 or its upstream now archives the old writing nodes and complete authorization records, and returns to planning mode.
2. A moved or deleted registered source could leave an active missing-file dependency with no public CLI recovery. `retire-input` now explicitly retires it after reopening, retaining its hash and excerpt metadata in history.
3. The live processing order could differ from the approved architecture while record checks still passed. It is now compared with the selected, frozen unit plan, without changing the approval-hash algorithm.
4. Whitespace-only review provenance was accepted. Review/authorization records and submitted summaries/checks now require nonblank strings.
5. A top-level JSON array could produce a traceback. Malformed-state and incomplete-installation diagnosis now return structured errors without rewriting the file.
6. Windows-style UTF-8 BOM JSON was rejected. Result manifests, selections and unit plans now accept it; Unicode paths and universal text newlines are exercised.

The current suite contains **94 tests**. The [CI workflow](../.github/workflows/tests.yml) runs them and a fresh, pip-free virtual-environment smoke test. See the actual [workflow runs](https://github.com/SAFuDarren/paper-shaper/actions/workflows/tests.yml) for results; the matrix definition alone is not evidence of success.

## Research-record checks

New work directories set `research_contract: "1"`. R02 must supply a frozen source
inventory and research map alongside its readable evidence/reference deliveries.
R04 options bind to the exact R02 map hash and the same IDs shown to the author.
Existing work directories keep their recorded contract; old approval snapshots are
not rewritten. Removing the new contract after approval invalidates that snapshot.

The source index follows selected literal TeX includes and bibliography and can
locate project-specific IDs using an explicit regex. A compact ID-family hint
summary exposes other result-like prefixes/variants that the chosen pattern misses;
it does not classify those IDs as scientific results. It leaves every generated
reading/candidate record pending. The AI must record actual selected reading,
claim conditions/status, candidate disposition and the rationale/source for each
relationship. Checks catch unaccounted candidates/files, changed sources, invalid
line ranges, unknown IDs, derivation cycles, missing inspected evidence and declared
conditional/gap steps mislabelled as a supported mainline. Motivation, limitation or
implementation links alone do not count as the central claim's evidence step.

Independent synthetic forward checks exercised the public tools and the R02/R04
delivery gate. They exposed the conditional-step mismatch and motivation-only
acceptance; both were repaired and rerun against a frozen code snapshot. These are
record-consistency tests, not evidence that a model understands arbitrary research.

The index is bounded text/regex discovery: binaries, generated/private/dependency
folders, files over 8 MiB and unsupported formats are reported as excluded. Custom
macros, unlabelled results, unsearched directories and inaccurate human/AI reading
records remain outside automatic verification. Inspect those exclusions and compare
an independent raw result index before claiming coverage. Accounting for each
candidate does not establish that every scientific result was discovered or proved.

## Horizontal workflow and optional-provider recheck

The overview is a five-step left-to-right flowchart with two revision loops. It
shows AI preparation and author decisions; its caption keeps planning as the
start mode and writing authorization scoped to a unit. Detailed contracts remain
in the stage configuration rather than being added to the skill entry.

A new isolated CLI check found that an optional provider missing before `start`
was accepted by `packet` but incorrectly rejected when its context was frozen.
The controller now freezes that provider as unavailable and permits direct-tool
fallback. A provider installed later is not silently activated; explicitly reopen
and bind it. Required missing providers and changes to providers that were
available at task start remain blocking. Two regression scenarios cover this
fallback and subsequent explicit activation.

## Efficiency measurements

A local, sequential comparison used a synthetic **32 MiB multiline text file**, selected **two lines**, and ran each operation **three times** with a warm filesystem. Environment: CPython 3.14.4, macOS 15.7.3 ARM64.

| Operation | Before: median time | After: median time | Before: peak Python memory | After: peak Python memory |
| --- | --- | --- | --- | --- |
| SHA-256 of the complete source | 18.657 ms | 17.316 ms | 32.002 MiB | 2.127 MiB |
| Build the task packet with a small excerpt | 121.326 ms | 19.828 ms | 65.523 MiB | 2.134 MiB |

The packet remained **3,777 characters** in this fixture, under the default 8,000-character limit. The skill entry at that audit was **22 lines / 1,836 characters**; the current entry keeps **22 lines / 1,985 characters**, including its contribution-first writing guidance. Hashing now streams chunks, selected text no longer splits the whole file into memory, and discovery computes its search roots once per capability lookup.

These are controller measurements on one machine, not process RSS, model token usage, manuscript quality or end-to-end research time. Complete registered files still have to be hashed for freshness; time grows with the bytes registered. The excerpt result is for a small selection in a multiline file, not a guarantee of constant memory for arbitrary huge individual lines or explicitly huge selections. No cross-invocation freshness cache is used.

Reproduce the synthetic microbenchmark from the repository root:

```sh
python3 tests/benchmark_controller.py --mib 32 --repeats 3
```

`--skill /path/to/another-version` runs the same harness against another complete skill folder. Allocation metrics are unavailable on interpreters without `tracemalloc`; timing and functional checks remain separate.

## Fresh-session behavior check

One paired, isolated synthetic trial compared the pre-audit and revised skills. Both received the same task: a registered source had moved, finish the current R02 evidence/reference delivery, use only public CLI operations, do not write prose, do not invent a new approval, and do not search online.

The old version could prepare evidence notes but could not start/submit R02 because the old missing input remained registered. The revised version retired that input through the CLI, preserved the old hash, registered the replacement, submitted R02 and stopped at `awaiting_review`. Both retained planning mode and avoided inventing human approval. The revised delivery distinguished fixture numbers, a conditional claim without a supplied proof, finite code checks, an open general case and an unverified reference.

Manual content inspection also found a minor filename-pointer mismatch in the revised evidence map: a prose reference used a hyphen where the delivered reference-inventory filename used an underscore. The manifest pointed to the correct file. Such text-level details still need review.

This is one targeted trial of recovery and author-review behavior. It is not a broad model benchmark or a judgment that the skill always identifies the best contribution or writing style. Model token/time telemetry was not supplied by the agent backend, so no model-efficiency statistic is reported.

## Practices borrowed from established skills

- [OpenAI skill-creator](https://github.com/openai/skills/blob/main/skills/.system/skill-creator/SKILL.md): keep the entry short, reveal details when needed, and use scripts for repeated deterministic operations. Here, the stage contracts, state checks and context budgets live in the controller.
- [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md): test realistic tasks against a prior version, inspect actual outputs and failures, and distinguish measurable behavior from human judgments. Here, the original passing suite was supplemented with failure scenarios and a targeted fresh-session comparison.
- [Superpowers writing-plans](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md): make scope, outputs and review points concrete. Here, each paper unit has a named delivery and author decision, while specialist skills remain optional.

These are design references, not endorsements or imported runtime dependencies. No third-party skill is bundled or automatically executed.

## Boundaries

The controller cannot authenticate a human message, prove that an AI read a source, verify all scientific claims or ensure literary judgment. Its context budget does not clear context already loaded by the host. Provider checks freeze the selected **entry-file hash**; referenced resources, external tools and services have their own version/dependency requirements. Only registered project inputs can be checked for changes.

The workflow retains these boundaries explicitly and leaves the corresponding content decisions with the author. Citation identity/support, publication requirements and output rendering still require real checks in the current project; an output role or a file's existence is not a substitute for those checks.
