---
title: Benchmarks
kind: log
status: current
updated: 2026-10-30
---

# Benchmarks

Numbers with a command and a machine. A change that touches the entry of a call shows here what it costs.

## Layer 1 call path, baseline before step 8 (2026-10-30)

The state measured: the static core before step 8 (a store shared by separately built artifacts, with a shared trap state), `dev` branch, nothing of step 8 built.

**Machine.** Intel(R) Xeon(R) Processor @ 2.80GHz, 4 CPUs (a shared virtual machine: Linux 6.18.44-fc-v185, x86_64, glibc 2.39). Compiler: cc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0, flags `-O2 -DNDEBUG`, no sanitizers, `-pthread`.

**Command.** `uv run python tools/bench_calls.py` (builds `tests/c/bench_calls.c` over six small wasm2c modules the way the product builds them; calibrates N for about 1 s per run; 5 runs of each case, the cases alternating; prints the median and min..max). The same command was run twice; the two tables follow.

| # | case | run 1 median | run 1 min..max | run 2 median | run 2 min..max | ns/call (run 1 / 2) |
|---|---|---|---|---|---|---|
| 1 | `wasmext_instance_call` of `add (i32,i32)->i32` (generic adapter, store enter/leave) | 18.61 M/s | 16.99..18.81 | 17.36 M/s | 15.27..19.58 | 53.7 / 57.6 |
| 2 | the same `add` through a link: `app.call_add` calls the import `libx.add` that `lib` answers (typed shim, TRAP_LINKED) | 8.73 M/s | 8.40..9.66 | 8.89 M/s | 6.41..9.75 | 114.6 / 112.5 |
| 3 | wasm calls an import answered by a uniform host function (`bind_func`) | 13.68 M/s | 11.54..14.38 | 13.16 M/s | 10.17..14.65 | 73.1 / 76.0 |
| 4 | wasm calls an import answered by a typed host function (`bind_typed`) | 15.52 M/s | 12.70..16.90 | 15.07 M/s | 10.70..15.31 | 64.4 / 66.4 |
| 5 | `call_indirect` through a shared table to a function of another instance (`owner.call(1)` reaches `user.nine`) | 16.45 M/s | 14.52..17.77 | 15.73 M/s | 11.56..17.32 | 60.8 / 63.6 |
| 6 | reference: `w2c_ops_add` called directly inside `WASMEXT_ENTER_PLAIN` / `WASMEXT_LEAVE_PLAIN` (no store) | 126.62 M/s | 111.15..136.22 | 129.37 M/s | 113.87..137.13 | 7.9 / 7.7 |

Reading the table:

- The medians of the two runs differ by 2 to 7 percent. The spread inside one run (min..max over 5 runs) is wider, up to about 35 percent for case 2 and case 4: on this machine compare medians, and treat a change under 10 percent as noise unless it repeats. A third run (not in the table) gave medians 18.21, 7.63, 12.42, 15.77, 17.89, 128.08 M/s, within the same ranges (case 2 was 13 percent under run 1).
- Cases 3, 4 and 5 include the call of the export that holds the import or the `call_indirect` (the same `wasmext_instance_call` as case 1), so what the import, the typed host function and the shared-table jump add on top of case 1 is the difference to case 1, not the whole number.
- Case 6 calls `w2c_ops_add` from another translation unit (no inlining), with the set-up of the trap (`setjmp`) on each iteration: it is the cost of the entry macros, not of the function.
- Each case calls a function of one or two instructions, so the numbers are the cost of the path, not of the work.

Files: `tools/bench_calls.py` (build, calibration, table), `tests/c/bench_calls.c` (the six cases, selected by an argument).

## Baseline for step 8b (2026-11-01, commit db92ac4)

The first table was taken on another machine (Xeon at 2.80 GHz); after a restart of the container the machine is a Xeon at 2.10 GHz, which is about 25 percent faster on these cases. Numbers of different machines are not compared: step 8b is measured on ONE machine, in one session, the commit before the step (db92ac4) against the commit after it, three runs each.

Command: `uv run python tools/bench_calls.py` (gcc 13.3.0, `-O2 -DNDEBUG`, no sanitizers, Linux 6.18, Python 3.11). Medians of 5 repetitions, three runs; ns per call:

| # | case | run 1 | run 2 | run 3 |
|---|---|---|---|---|
| 1 | `wasmext_instance_call` of `add` | 38.5 | 39.4 | 42.3 |
| 2 | through a link (typed shim) | 87.1 | 80.1 | 79.2 |
| 3 | import answered by a uniform host function | 54.9 | 55.3 | 56.0 |
| 4 | import answered by a typed host function | 46.3 | 46.4 | 46.8 |
| 5 | `call_indirect` through a shared table to another instance | 41.7 | 42.3 | 40.8 |
| 6 | reference: `w2c_ops_add` in `ENTER_PLAIN`/`LEAVE_PLAIN` | 4.8 | 4.5 | 5.3 |

Rule of 8b (S0008): a change over 10 percent on case 1 or 2 against this baseline, on the same machine, repeated in two runs, is a regression and stops the sub-step; the noise inside one run is up to 10 to 35 percent, so the comparison is of medians over three runs.

Cases 7 and 8 (S0008, written in 8b-1): two position-independent shared libraries built apart (the test artifacts of `tests/test_artifacts.py`, hidden visibility, each with its own copy of the core and of the runtime): artifact A makes the store and B attaches. 7 is a call of `add` of an instance of B (`ops`) in the store of A; 8 is the call of `call_add` of B's `app`, whose import `libx.add` is answered by A's `lib` (a link across artifacts, typed shim). Both call by the NAME of the export through the table of artifact B (`B->call`: it has no call by index), so each includes a search of the exports and the cases are compared with each other and with the same case on another commit, not with cases 1 and 2. Baseline at db92ac4 is below, measured by applying only `tools/bench_calls.py` and `tests/c/bench_calls.c` to a checkout of that commit (with `core_build_macros` replaced by the fusedwasi macro alone, which is all the builders passed then).

## Step 8b-1: the runtime table and the forwarders (2026-11-02, working tree on top of 534fb88)

The entry is not touched in 8b-1 (the forwarders are off the path of a call), so cases 1 and 2 are expected to stay as they are. Same machine as the baseline above (Xeon at 2.10 GHz, 4 CPUs, gcc 13.3.0, `-O2 -DNDEBUG`, no sanitizers), `uv run python tools/bench_calls.py` (5 repetitions of about 1 s each, the cases alternating). Three runs of the working tree and three of db92ac4 (with only the benchmark files applied, see above) alternated in time: H1 B1 H2 B2 H3 B3. ns per call, one value per run, then the median of the three:

| # | case | 8b-1 run 1 / 2 / 3 | median | db92ac4 run 1 / 2 / 3 | median |
|---|---|---|---|---|---|
| 1 | `wasmext_instance_call` of `add` | 40.4 / 39.1 / 38.1 | 39.1 | 40.5 / 38.7 / 39.8 | 39.8 |
| 2 | through a link (typed shim) | 89.6 / 76.9 / 78.3 | 78.3 | 81.8 / 73.7 / 77.9 | 77.9 |
| 3 | import answered by a uniform host function | 55.5 / 54.1 / 57.4 | 55.5 | 58.8 / 58.0 / 55.1 | 58.0 |
| 4 | import answered by a typed host function | 51.6 / 48.0 / 46.8 | 48.0 | 47.1 / 50.3 / 46.3 | 47.1 |
| 5 | `call_indirect` through a shared table | 52.4 / 38.2 / 41.4 | 41.4 | 39.4 / 40.1 / 40.9 | 40.1 |
| 6 | reference: `w2c_ops_add` in `ENTER_PLAIN`/`LEAVE_PLAIN` | 4.7 / 5.1 / 5.0 | 5.0 | 4.9 / 4.5 / 4.7 | 4.7 |
| 7 | B's `add` in A's store (two artifacts, by name) | 48.0 / 51.7 / 47.5 | 48.0 | 52.7 / 44.8 / 52.2 | 52.2 |
| 8 | the same through a link (B's `app` to A's `lib`) | 98.9 / 91.0 / 90.3 | 91.0 | 104.4 / 87.7 / 91.4 | 91.4 |

The medians of cases 1 and 2 differ from the baseline by 2 percent and 0.5 percent, inside the noise of the table (one run moves a case by 10 to 20 percent; the min..max of the 5 repetitions inside a run is wider still). Nothing here is a claim of a regression or of an improvement. The numbers of cases 7 and 8 at 8b-1 and at db92ac4 are the baseline for 8b-2, which changes the entry.
