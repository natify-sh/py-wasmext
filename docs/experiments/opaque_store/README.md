# Opaque store through a table of pointers: cost on the hot path (PROTOTYPE)

Throwaway prototype, nothing here is product code and nothing in `src/`, `tests/`, `tools/` was changed. The results are for the decision about S0008
(opaque store via a table vs inline struct + layout hash). Threshold of the owner: more than 10 percent on case 1 or 2 means the inline design stays.

## Method
`uv run python docs/experiments/opaque_store/run.py` imports `tools/bench_calls.py` (unchanged) and builds the same program three times over the same
modules (ops/app/lib), flags `-O2 -DNDEBUG`, no sanitizers. `bench_proto.c` is a copy of `tests/c/bench_calls.c` plus 6 lines (table lookup at start).
Calibration on A (same n for all variants), 5 repetitions of about 1 s, alternating A/B/C inside each case.
* A: as the product (store functions inline).
* B: `wasmext_store_enter`, `wasmext_store_leave`, `wasmext_store_host_lock` (the last takes the store mutex) are indirect calls through `proto_tab`,
  whose functions are in `store_lib.c`, a separate `-fPIC -fvisibility=hidden` shared library (the unchanged inline code inside; the table comes from
  one exported getter). `proto_ops.h` does it by renaming the originals before the headers are read, so every user in `wasmext_instance.h` and in the
  generated bindings (shim `begin_`/`end_`) goes through the table. Indirect calls per call: case 1 = 3 (enter, host_lock, leave); case 2 = 7 (the call
  3, the shim `begin_` enter + host_lock, the shim `end_` host_lock + leave). The thread-ready check, `rlock_depth`/`release_to`, the thread-local
  `line_of_` stay as in the product (the last one now lives in the library). `check_refs`/`fill_refs` take the store but do nothing for `add`.
* C: the whole `wasmext_instance_call` is one indirect call into the library (case 1: 1 indirect call; case 2: 1, the shim's nested enter/leave stay
  inline, as the shim is code of the artifact). The library needs `-rdynamic` on the program (`wasm_rt_init` and the thread flag live there).
* Mutation check: store_lib `enter` made to return -1 -> `wasmext_instance_instantiate(ops) == 0` fails, so B really runs the library code.

## Results (Intel Xeon @ 2.80GHz, 4 CPUs, gcc 13.3.0, Linux 6.18, python 3.11)
Command: `uv run python docs/experiments/opaque_store/run.py` (run twice, back to back)

Run 1
| case | variant | calls/s median | min..max | ns/call | % over A |
|---|---|---|---|---|---|
| 1 | A inline | 19.47 M | 18.48..20.13 M | 51.4 | +0.0 |
| 1 | B table (store ops) | 17.68 M | 15.41..18.43 M | 56.6 | +10.1 |
| 1 | C table (whole call) | 17.64 M | 16.09..18.10 M | 56.7 | +10.3 |
| 2 | A inline | 9.72 M | 9.44..10.04 M | 102.9 | +0.0 |
| 2 | B table (store ops) | 8.74 M | 8.13..9.25 M | 114.5 | +11.2 |
| 2 | C table (whole call) | 9.08 M | 8.46..9.53 M | 110.1 | +7.0 |

Run 2
| case | variant | calls/s median | min..max | ns/call | % over A |
|---|---|---|---|---|---|
| 1 | A inline | 19.13 M | 18.84..20.48 M | 52.3 | +0.0 |
| 1 | B table (store ops) | 17.74 M | 16.84..18.09 M | 56.4 | +7.8 |
| 1 | C table (whole call) | 17.64 M | 16.20..17.92 M | 56.7 | +8.4 |
| 2 | A inline | 9.83 M | 9.03..9.93 M | 101.8 | +0.0 |
| 2 | B table (store ops) | 8.82 M | 8.25..9.07 M | 113.4 | +11.5 |
| 2 | C table (whole call) | 9.22 M | 7.99..9.34 M | 108.4 | +6.6 |

## Reading
* One indirect call (B minus A over the number of indirect calls): case 1 about 4.1..5.2 ns / 3 = 1.4..1.7 ns; case 2 about 10.6..11.6 ns / 7 = 1.5..1.7 ns.
* Case 1 B: +10.1 and +7.8 percent (right at the threshold, noise of the machine is of the same size: A min..max alone spans about 9 percent).
  Case 2 B: +11.2 and +11.5 percent: over 10 percent in both runs.
* C is not cheaper than B on case 1 although it has one indirect call instead of three: the cost is not only the call, the inline code moved into the
  library also pays for a shared-library TLS access (`__tls_get_addr`, `line_of_`) and symbol indirection; so "fewer indirect calls" does not help much.
* Verdict: case 2 with the table for the store ops is over 10 percent (about 11 percent) in both runs; case 1 is at the line (8 and 10 percent).
  Under the rule "more than 10 percent on case 1 or 2 means inline stays", the inline design stays. Caveats: one machine, one compiler, a library
  separate from the program (a table whose functions the compiler could see in the same artifact would be cheaper, but then it is not one place).
