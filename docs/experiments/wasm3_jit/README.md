# A template JIT for the metacode of wasm3 (x86-64): a time-boxed prototype

Date: 2026-11-16, one container (Xeon 2.3 GHz, gcc -O2). The question came from the JSLinux comparison (`../jslinux_x64`): wasm3 is the engine for devices where a JIT is forbidden (iOS, Pythonista), and 10x behind wasmtime. Could its "metacode" be compiled to native code, and how much would that give? Nothing here is part of wasmext or of wasmhost; this is a measurement.

## Result (one kernel, 200 M iterations)

| engine | M iterations/s |
|---|---:|
| wasm3 interpreter | ~119 (113-127 over runs) |
| wasm3 + this prototype | **~636** (about 5.3x) |
| wasmtime-py (`bench_wasmtime.py`) | ~750 |
| native C -O2 (`kernel_native.c`) | ~1260 |

The result equals the interpreter's on every call (n=200000000: 44079651, then 3119693121, 3937610238 because linear memory persists between calls; n=1000 also). The out-of-bounds path is generated but **not tested**.

**What this does not show:** the kernel is one loop of 11 kinds of operations, no calls, no branches inside the body, no 64-bit or float, no `memory.grow`. Real programs (the JSLinux emulator, CoreMark in the guest) have thousands of other operations and calls; the 5.3x is **not** a prediction for them. The prototype also needs writable and executable memory, which iOS does not give, so it does not serve the device that motivated it (it would serve a Linux or macOS server that runs wasm3 for another reason).

## Files

* `kernel.wat` / `kernel.wasm`: `acc = acc*31 + mem[i&1023] + i; mem[(i*7)&1023] = acc; i++` while `i < n`.
* `jit_bench.c`: the prototype and the timing driver. It finds `Loop` .. `ContinueLoopIf` in `fn->compiled`, decodes the operations by name, emits x86-64 into an RWX `mmap` page and overwrites the pointer of `Loop` with `JitRun`, which calls the native code and continues at the operation after `ContinueLoopIf`. `out/jit_bench kernel.wasm kernel N REPS USEJIT`.
* `dump.c`: prints the metacode of a function with the names of the operations.
* `jit_opname.inc`: the ONLY change to wasm3's own source: append it to `source/m3_compile.c` (it maps the address of an operation to its name; 715 operations; generated from the `op_*` names).
* `bench.c`, `kernel_native.c`, `bench_wasmtime.py`: the baselines.

## Reproduce

```
git clone https://github.com/wasm3/wasm3 && git -C wasm3 checkout 28ecb9a    # MIT
cp -r wasm3/source work && cat jit_opname.inc >> work/m3_compile.c
SRC=$(ls work/m3_*.c | grep -v 'api_\|tracer')
gcc -O2 -w -Iwork -DNDEBUG jit_bench.c $SRC -lm -o jit_bench
gcc -O2 -w -Iwork -DNDEBUG dump.c      $SRC -lm -o dump
gcc -O2 -w -Iwork -DNDEBUG bench.c     $SRC -lm -o bench_w3
gcc -O2 kernel_native.c -o kernel_native
./jit_bench kernel.wasm kernel 200000000 3 0     # the interpreter
./jit_bench kernel.wasm kernel 200000000 3 1     # the JIT
```

## The metacode of the kernel (`./dump kernel.wasm kernel`)

```
Entry | CopySlot_32 5 6 | Loop
i32_Multiply_ss 7 5 | SetSlot_i32 12 | u32_And_ss 8 4 | i32_Load_u8_r 0 | i32_Add_rs 12
i32_Add_rs_f 4 5 | i32_Multiply_ss 9 4 | u32_And_rs 8 | i32_Store_u8_sr 5 0 | i32_Add_ss_f 6 4 4
u32_LessThan_ss 2 4 | ContinueLoopIf <ptr> | CopySlot_32 0 5 | Return
```

## Facts needed to extend it (verified by reading `m3_exec.h` and by running)

* The stream is 8-byte words; operands are 32-bit values in them (the upper half is garbage: mask it).
* **Slots are 4 bytes** (`m3slot_t = u32`), so slot k is at `sp + 4*k`; a 64-bit value takes two slots. Getting this wrong gave a silent wrong result (loop ran 0 times, result 1). Constants are copied into slots by `Entry`, so the JIT reads them as slots.
* Op signature: `m3ret_t op(pc_t pc, m3stack_t sp, M3MemoryHeader* mem, m3reg_t r0 [, f64 fp0])`, chained by tail calls. Linear memory is at `mem+1`, `mem->length` is its size. Return 0 is ok, else a trap string.
* Operand order: `_rs`: `r0 = slot OP r0`. `_ss`: the first stream word is operand2's slot, the second is operand1's; the result goes to r0. `_sr`: `r0 OP slot`. The `_f` (fold) variants take a destination slot as the last word and write it **and** r0. Stores `_sr`: value slot, then offset, address in r0. Loads `_r`: the offset, address in r0.
* Generated code uses rbx = sp, r12 = memory data, r13 = memory length, eax = r0.
* Missing for a real version: calls, branches inside the body, `memory.grow` (the interpreter refreshes `_mem` per loop iteration), 64-bit and float, W^X, other CPUs, a test of the trap path.
