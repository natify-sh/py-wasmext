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
