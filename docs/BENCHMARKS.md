---
title: Benchmarks
kind: log
status: current
updated: 2026-11-04
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

The entry is not touched in 8b-1, but the forwarders ARE on the path of a call: every adapter, shim and `instantiate` calls `wasm_rt_set_unwind_target` (a forwarder now), a generated `try` calls get/set, and in a position-independent build a forwarder adds a `__tls_get_addr` call. So cases 1 and 2 are not expected to stay as they are by argument; the measurement below says they stayed within noise, and that is all it says. The entry of 8b-2 will do the unwind slot inline. Same machine as the baseline above (Xeon at 2.10 GHz, 4 CPUs, gcc 13.3.0, `-O2 -DNDEBUG`, no sanitizers), `uv run python tools/bench_calls.py` (5 repetitions of about 1 s each, the cases alternating). Three runs of the working tree and three of db92ac4 (with only the benchmark files applied, see above) alternated in time: H1 B1 H2 B2 H3 B3. ns per call, one value per run, then the median of the three:

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

## Step 8b-2: the entry on the runtime of the store (2026-11-04, working tree on top of 6d4fe1f)

Same machine as above (Xeon at 2.10 GHz, 4 CPUs, gcc 13.3.0, `-O2 -DNDEBUG`, no sanitizers), `uv run python tools/bench_calls.py`, medians of 5 repetitions of about 1 s, ns per call. "Before" is the commit 6d4fe1f (8b-1, the commit before the step), two sets of three runs, one at the start of the session and one (with `git stash`) after the runs of the work tree; "after" is the work tree, three runs. Case 6 changed with the step: it was `w2c_ops_add` in `ENTER_PLAIN`/`LEAVE_PLAIN`, which does not link any more in a build of the core (`g_wasm_rt_jmp_buf` is gone with the trap handler), so it is now the same function in `ENTER_STORE`/`LEAVE_STORE` and the two numbers are not comparable.

| # | case | before, set 1 (3 runs) | median | before, set 2 | median | after (3 runs) | median |
|---|---|---|---|---|---|---|---|
| 1 | `wasmext_instance_call` of `add` | 38.7 / 37.9 / 39.3 | 38.7 | 36.7 / 35.7 / 39.3 | 36.7 | 40.9 / 42.8 / 38.7 | 40.9 |
| 2 | through a link (typed shim) | 74.2 / 73.1 / 74.3 | 74.2 | 73.6 / 75.5 / 75.0 | 75.0 | 69.9 / 67.7 / 68.7 | 68.7 |
| 3 | import answered by a uniform host function | 53.3 / 53.9 / 55.9 | 53.9 | 54.3 / 55.4 / 53.0 | 54.3 | 50.4 / 50.5 / 50.7 | 50.5 |
| 4 | import answered by a typed host function | 46.2 / 44.4 / 45.0 | 45.0 | 43.0 / 44.1 / 44.2 | 44.1 | 40.2 / 41.8 / 41.6 | 41.6 |
| 5 | `call_indirect` through a shared table | 38.5 / 38.8 / 40.8 | 38.8 | 37.8 / 38.3 / 39.3 | 38.3 | 41.1 / 38.4 / 42.1 | 41.1 |
| 6 | the entry alone (see above: not the same code) | 4.5 / 4.7 / 4.5 | 4.5 | 4.5 / 4.6 / 4.5 | 4.5 | 8.3 / 8.0 / 8.1 | 8.1 |
| 7 | B's `add` in A's store (two artifacts, by name) | 44.7 / 47.0 / 45.6 | 45.6 | 46.0 / 46.4 / 45.4 | 46.0 | 65.8 / 59.6 / 65.8 | 65.8 |
| 8 | the same through a link (B's `app` to A's `lib`) | 91.1 / 86.5 / 92.5 | 91.1 | 92.4 / 91.3 / 90.7 | 91.3 | 119.8 / 118.4 / 122.4 | 119.8 |

The gate (S0008, D-8):
* Case 1 against the baseline of db92ac4 (39.4): +3.8 percent by the median of the three runs (the runs: +3.8, +8.6, -1.8). Against the two before-sets of the session: +5.7 and +11.4 percent by medians (+11.4 and +16.6 percent in the two runs that are above the second set's median). The reading against db92ac4 is inside the rule; the reading against the same-session runs is on the line, and it is not noise by itself: case 6 shows the entry alone costs 3.6 ns more (it saves the unwind target by a call and sets it by another, and `wasmext_enter_` reads `tls.rt`).
* Case 2 against db92ac4 (80.1): -14 percent (better), against the sessions' before-sets -7 and -8 percent. The typed shim of 8b-2 does the same entry as an adapter, so case 2 should not be faster by design; read it as inside the noise of this machine, not as a gain.
* Cases 7 and 8 (reported, and stopping by the maintainer's answer of 2026-11-02): +44 and +32 percent against set 1 (+43 and +31 against set 2), in all three runs: **over 10 percent in two runs, so the sub-step is stopped.** Where it goes (read from the code, not measured): a call into a store that has two copies takes the slow path of the activation: the thread-ready flag, `tls.rt` of this copy, a call of `activate` of the other copy and its `deactivate` (each a computation of the address of a thread-local variable of a position-independent library, which is a call), `rt->enter` and `rt->leave` of the other copy (each with its own TLS address and two calls for the unwind target). Case 8 does it twice (the call and the shim).
* What to try before asking for a new rule (NOT done: the budget of the step; each needs its own measurement): publish the address of `g_unwind_target` in `wasmext_tls` (the design says so; it takes the two calls out of the entry, which is also the +3.6 ns of case 6); move `wasmext_thread_ready_` into `wasmext_tls` (one address computation less on every call); read `wasmext_tls_` once in an activation and pass the pointer; `-ftls-model=initial-exec` for the artifacts of the core on Linux (a position-independent library with hidden thread-locals; not for a library loaded late with `dlopen`); the saved values of the peers only when they differ from what `activate` would set.

### Step 8b-2, second round: the cheap changes (2026-11-04)

A third before-set of the commit before the step (`git stash`, same session, three runs) and the work tree after each change, three runs each, medians, ns per call. (a) = skip the restore of a peer that was on that runtime already; (b) the address of `wasmext_tls_` read once in an activation; (c) `unwind_slot` and `ready` in `wasmext_tls` (the entry saves and sets the unwind target without a call; `wasmext_thread_ready_` is gone); (d) `-ftls-model=initial-exec` in the flags of the benchmark build ONLY (not kept).

| set | case 1 | case 2 | case 6 | case 7 | case 8 |
|---|---|---|---|---|---|
| before (3 runs) | 37.5 / 38.8 / 38.3 (38.3) | 77.0 / 77.2 / 76.4 (77.0) | 4.5 | 46.8 / 47.5 / 48.3 (47.5) | 86.4 / 90.5 / 84.5 (86.4) |
| after the first round | 40.9 / 42.8 / 38.7 (40.9) | 68.7 | 8.1 | 65.8 (59.6..65.8) | 119.8 |
| + (a) | 42.9 / 41.4 / 40.1 (41.4) | 71.3 | 8.3 | 65.1 / 64.0 / 64.5 (64.5) | 119.5 / 115.5 / 114.6 (115.5) |
| + (a)(b) | 40.4 / 40.3 / 39.1 (40.3) | 69.5 | 8.4 | 62.7 / 63.2 / 61.2 (62.7) | 117.7 |
| + (a)(b)(c) | 38.6 / 39.7 / 39.9 (39.7) | 65.7 | 6.2 | 59.3 / 56.6 / 58.7 (58.7) | 100.8 / 97.9 / 95.9 (97.9) |
| (a)(b)(c) + (d), bench build only | 41.0 / 39.3 / 39.0 (39.3) | 69.2 | 6.3 | 51.6 / 48.7 / 51.0 (51.0) | 81.4 / 82.6 / 86.0 (82.6) |

(a) did not move anything beyond the noise and is NOT kept (it needed a marker value in the answer of `activate`). (b) is kept: it moves nothing alone, it is the base of (c). (c) is kept: case 6 (the entry alone) goes from 8.1 to 6.2 ns, case 7 from 62.7 to 58.7, case 8 from 117.7 to 97.9. Against the before-set: case 1 +3.7 percent, case 2 -15 percent (the shim of 8b-2 is not designed to be faster; noise of this machine), **case 7 +24 percent and case 8 +13 percent: both still over 10 percent.** Against db92ac4 (39.4 / 80.1): case 1 +0.8 percent, case 2 -18 percent.

The gate on cases 7 and 8 was accepted by the maintainer on 2026-11-04 as an exception, for these reasons: the path is new (before 8b-2 a trap across copies was an abort, so no old number exists), the remaining cost is the dynamic TLS model of a position-independent library, and cases 1 and 2 are inside the rule (see S0008, D-8).

Where the rest of cases 7 and 8 goes: with (d) the same code costs +7 percent (case 7) and -4 percent (case 8). So what is left is the dynamic TLS model of a position-independent library: an access to a thread-local variable of the library is a call of `__tls_get_addr` (about 1.6 ns here: the 11 ns of case 7 over about 7 accesses). The slow path of case 7 makes seven: the activation of the entering copy (1), `activate` of the other copy (1), the enter and the leave in the entering copy (1 + 1) and in the runtime's copy through the table (1 + 1), the deactivation (1); case 8 does it twice, with the shim. These are counted from the code and divided into the measured difference, not measured one by one (no `perf` here). (d) cannot be assumed by a product build: a library loaded with `dlopen` (a Python extension) may not use the initial-exec model unless the static TLS block has room, so it is not part of the product flags in this step. The choices left to the maintainer: accept the cost of the cross-artifact slow path (a new capability: before 8b-2 a trap across copies was an abort, so there is no old number), or have the other copy's `enter`/`leave` do their TLS access once (a single call that does activate, enter and the unwind save for the pair, about 3 accesses less), or keep the thread record of each copy reachable from the store per thread.
