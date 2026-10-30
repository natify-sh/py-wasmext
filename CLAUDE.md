# CLAUDE.md

Rules for working on this repository with an agent. The maintainer talks Ukrainian; code, comments,
commit messages and documents are in English.

## Read first
* `docs/layers.md`: the cut into layers and the **order of work** (layer 1 steps 1 to 12, then layers 2 and 3).
* `docs/DECISIONS.md`: what was decided and why (`Dn`). Do not re-open a decision without a new `Dn` that supersedes it.
* `docs/LESSONS.md`: traps already found. Read before touching C, the generator, CI or the tests.
* `docs/specs/`: the contracts (`Snnnn`). A contract is changed in its spec first.

## Principles (from the maintainer)
* Take an unmodified wasm module for a standard target and run it. Build bottom-up: the static C core (layer 1) is complete and tested from C
  before the shared C API (layer 2) and the front ends (layer 3).
* An existing piece is not patched on the side. If it needs a change it is taken when the plan reaches its step, or the change is a
  new `Dn` with the reason. The register of duplicates is in `docs/layers.md`.
* ABI is free to change in alpha; `abi/current.json` and the fingerprint in `src/wasmext/_abi.py` follow every change of `src/wasmext/c/`.
* Free-threaded safety is a requirement of layer 1. `ctypes` uses `CDLL`, never `PyDLL`.
* The tests build what the product builds: the C of wasm2c goes through the repairs of `_natify`, and the runtime through its wrappers
  (`tests/test_instance_core.py`, fixture `build`). Raw wasm2c output is not a test subject.
* Measure, do not estimate. A speed claim has a command, a machine and numbers in `docs/BENCHMARKS.md`; a behaviour claim has a test.
* A test is not trusted until a mutation of the code it covers fails it **for the right reason** (read the message; a compile error is not a catch).

## How work is organised: one orchestrator, subagents do the steps
The main session is the **orchestrator**. It does not implement a step itself: it picks the step, writes the brief, hands it to a subagent,
**verifies** the result, fixes what is wrong, keeps the documents true and asks the maintainer. It may fix a small mistake itself
(about 20 lines, obvious). Anything larger goes back to a subagent with a precise list.

| role | model | agent (`.claude/agents/`) | typical work |
|---|---|---|---|
| orchestrator (main session) | strongest available | | choose the step, brief, verify, small fixes, documents, push, CI |
| implementer | sonnet | `implementer` | one scoped step: code, tests, mutation checks |
| reviewer | opus | `reviewer` | independent read of a high-stakes diff with a fresh context (ABI, contracts, traps, ownership, threads) |
| runner | haiku | `runner` | run suites and benchmarks, report numbers, group failures, mechanical edits |

A step is **one goal that a command confirms**. The orchestrator verifies by running the acceptance commands **itself**, reading the diff
(inside the scope? under the budget? nothing unrelated?), and checking the documents. A change to a contract (the record `wasmext_export`,
`wasmext_binding`, the descriptor, the trap state, the store layout) needs an `approved` spec **before** code, and a `reviewer` reads the diff
with no access to the implementer's reasoning. A subagent that needs more than its scope or budget, or sees two designs, **stops and reports**.

### The brief
```
Goal:        <one sentence, as a result a command shows>
Context:     <what exists, which files; what was tried and ruled out>
Read first:  <the 1-3 documents or files that matter>
Scope:       <files that may change>        Out of scope: <what must not change>
Budget:      <~N lines of diff; stop and report if more is needed>
Acceptance:  <exact commands + expected result>
Report:      files changed, commands run with output, numbers, open questions
```

## Before every push (the orchestrator runs these)
`uv run ruff check . && uv run ruff format .` and `uv run pyright`; the ABI tests (`tests/test_abi.py`, `tests/test_abi_declaration.py`) and the suites
`test_descriptor.py`, `test_store_core.py`, `test_instance_core.py`, `test_model_wasi_mapping.py` with `CC=cc` and `CC=clang`; the strict header check
`.github/scripts/layer1_check.c` (gcc, clang). When `src/wasmext/c/` changed: update the fingerprint (`uv run pytest tests/test_abi.py`) and
`uv run python -m tests.abi_surface --update`. After the push, check **all seven workflows** on the head (per workflow `conclusion`; Windows and macOS jobs
of Pre-commit and Python versions are the ones that find new things); one network timeout (`ETIMEDOUT`) in Example wheels is re-run once.
A step is closed when CI is green on its head, not before.

## Against over-engineering (every agent)
The smallest change that makes the acceptance command pass. No code for later. No new module, layer or option the brief does not name.
No drive-by reformatting. When unsure between two designs, implement neither: report both with their costs.
