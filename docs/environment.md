# Python and operating systems

[README](../README.md) · [中文说明](../README.zh-CN.md)

PaperShaper's controller requires **Python 3.9 or newer** and uses only the standard library. No `pip install`, API key, model service or package manager is required. Install the complete skill folder: `scripts/` and `config/` are needed alongside `SKILL.md`.

Prefer a maintained CPython release. At the 2026-11-06 audit, Python's official supported-version list covers 3.11–3.15; 3.9/3.10 remain compatibility targets here. See the [Python version status](https://devguide.python.org/versions/). Support status and downloadable patch versions can change; CI selects a minor version and records the actual interpreter.

## Choose the interpreter

Use the Python in the environment where you intend to work. The launcher name differs by system:

| Environment | Common invocation |
| --- | --- |
| macOS or Linux | `python3 /path/to/paper-shaper/scripts/framework.py doctor` |
| Windows Python launcher | `py -3 C:\path\to\paper-shaper\scripts\framework.py doctor` |
| Windows with Python on PATH | `python C:\path\to\paper-shaper\scripts\framework.py doctor` |
| Activated virtual environment | `python /path/to/paper-shaper/scripts/framework.py doctor` |
| uv-managed execution | `uv run python /path/to/paper-shaper/scripts/framework.py doctor` |
| Named Conda environment | `conda run -n YOUR_ENV python /path/to/paper-shaper/scripts/framework.py doctor` |

Quote paths that contain spaces. `doctor` reports the actual interpreter, version, implementation, environment prefix and virtual-environment status. With a work directory, it also checks existing workflow records without changing them:

```sh
python3 /path/to/paper-shaper/scripts/framework.py doctor /path/to/paper-work
```

The uv and Conda rows describe how to select an interpreter. CI tests standard interpreters and standard-library virtual environments; it does not separately certify every package manager, host application or optional skill.

## CI coverage

The [test workflow](../.github/workflows/tests.yml) runs 18 configurations:

| Runtime | Linux | Windows | macOS |
| --- | --- | --- | --- |
| CPython 3.11, 3.12, 3.13, 3.14, 3.15 | Every listed minor | Every listed minor | Every listed minor |
| CPython 3.9, 3.10 | Compatibility checks | Outside this matrix | Outside this matrix |
| PyPy 3.11 | Compatibility checks | Outside this matrix | Outside this matrix |

Every configuration runs the controller tests and a smoke test in a fresh environment **without pip or installed dependencies**, using Unicode and space-containing paths. UTF-8 JSON, UTF-8 BOM JSON, Unicode source files and Windows line endings have regression coverage. Python-allocation memory checks are skipped when an interpreter does not provide `tracemalloc`; the functional tests still run.

Runner labels identify changing hosted images, rather than one permanent OS build. In the audit, `macos-latest` uses ARM64. The matrix does not claim separate macOS Intel, Windows ARM64, free-threaded/debug Python, development releases or all Linux distributions have been tested. Consult the actual [GitHub Actions run](https://github.com/SAFuDarren/paper-shaper/actions/workflows/tests.yml) for current results and selected patch versions. Availability was checked against the official [Python builds](https://github.com/actions/python-versions/blob/main/versions-manifest.json) and [PyPy releases](https://downloads.python.org/pypy/versions.json).

## Text files and project paths

- Controller records are written as UTF-8. User JSON accepts UTF-8 with or without a BOM, including result manifests, option selections and unit plans.
- Selected source excerpts must be UTF-8 text, optionally with a BOM. LF, CRLF and CR newlines work. Convert or extract other encodings and binary formats using the host or a suitable skill; the controller does not guess an encoding or parse PDFs.
- State files contain project and provider locations. Running on different systems is supported; copying an existing approved work directory to a different machine does **not** automatically rebind its absolute paths or approvals.
- Optional specialist skills have their own tools, dependencies and licenses. Core controller compatibility is separate from those providers' requirements.

## Recovery

`doctor` does not rewrite decisions, repair approvals or remove locks. Preserve the original file before restoring a known-valid state backup. Do not hand-edit approval hashes to make a broken record pass.

For registered material changes, use `reopen` on the earliest affected task. If a file was moved or intentionally removed, retire the old input explicitly, preserving its hash in history, then register its replacement:

```sh
python3 scripts/framework.py reopen ./paper-work --node R02 --reason "Source was relocated"
python3 scripts/framework.py retire-input ./paper-work --path old/results.md --reason "Replaced by data/results.md"
python3 scripts/framework.py attach ./paper-work --path data/results.md --material-id results --start 1 --end 20
python3 scripts/framework.py start ./paper-work
```

`retire-input` cannot rewrite a working or delivered task. It removes the current input and excerpts only after explicit reopening; earlier records remain in history. `detach` has a different purpose: it removes an excerpt from context while retaining the source as an active dependency.

Reopening R05 or any of its upstream decisions retires old writing nodes and revokes their authorizations, including reused unit IDs. After approving the revised architecture, authorize the intended units and modes again. A lock left by a stopped process needs an owner/process check before removal; the controller never deletes it automatically.
