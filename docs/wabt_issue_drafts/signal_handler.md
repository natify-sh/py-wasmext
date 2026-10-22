> **Status (2026-10-22): opened; the maintainers agreed to close it as not the intended use (wasm-rt is one implementation per program; users who need another build their own). The text below is kept as it was posted. Its first sentence about "every module translated by wasm2c" describes wasmext's build, not wasm2c's intended use.**

# Title

wasm2c runtime: a second module in the process takes over the SIGSEGV handler, and a fault in the first module aborts the process

# Body

## Summary

Every module translated by `wasm2c` is built with its own copy of `wasm-rt-impl.c`. `wasm_rt_init()` of each copy installs a `SIGSEGV`/`SIGBUS` handler
with `sigaction(..., &sa, NULL)`: the previous action is thrown away and never called. When two modules (each with its own copy of the runtime, for
example two plugins loaded as shared libraries) are set up in one process, the handler is the one of the module set up **last**. An out-of-bounds access in the
*other* module is then handled by the wrong copy of the runtime, and the process aborts instead of the call trapping.

(The same code also replaces any handler the application already has, e.g. a crash reporter, without a way to chain to it.)

## Steps to reproduce

Linux, gcc. `BIN` is a directory with `wat2wasm` and `wasm2c`, `RT` is the `wasm2c/` directory of the WABT sources (the runtime files).

```sh
BIN=/path/to/wabt/bin
RT=/path/to/wabt/wasm2c

cat > m.wat <<'EOF'
(module
  (memory 1)
  (func (export "oob") (result i32) (i32.load (i32.const 0x7ffffff0))))
EOF
$BIN/wat2wasm m.wat -o m.wasm
for n in a b; do $BIN/wasm2c m.wasm -o $n.c --module-name=$n; done
```

A "plugin" is one module with its own copy of the runtime behind two functions (built twice, as `liba.so` and `libb.so`; the symbols of the runtime are
hidden so that each library really has a copy of its own):

```c
/* lib.c  (NAME is replaced by a or b) */
#include <wasm-rt.h>
#include <wasm-rt-exceptions.h>
#include <wasm-rt-impl.h>
#include "NAME.h"
static w2c_NAME inst;
__attribute__((visibility("default"))) void NAME_setup(void) { wasm_rt_init(); wasm2c_NAME_instantiate(&inst); }
/* 0 if the call trapped and the trap was caught here, 1 if it returned */
__attribute__((visibility("default"))) int NAME_oob(void) {
    wasm_rt_trap_t code = wasm_rt_impl_try();
    if (code) return 0;
    w2c_NAME_oob(&inst);
    return 1;
}
```

```c
/* host.c */
#include <stdio.h>
#include <string.h>
void a_setup(void); int a_oob(void);
void b_setup(void); int b_oob(void);
int main(int argc, char **argv) {
    a_setup();
    b_setup();   /* b was set up last: the SIGSEGV handler is now the one of b's copy of the runtime */
    int use_b = argc > 1 && !strcmp(argv[1], "b");
    printf("calling %s_oob() ...\n", use_b ? "b" : "a");
    fflush(stdout);
    int returned = use_b ? b_oob() : a_oob();
    printf("%s_oob() %s\n", use_b ? "b" : "a", returned ? "returned" : "trapped (as it should)");
    return 0;
}
```

```sh
for n in a b; do
  sed "s/NAME/$n/g" lib.c > lib_$n.c
  gcc -O1 -shared -fPIC -fvisibility=hidden -I$RT -I. -o lib$n.so lib_$n.c $n.c \
      $RT/wasm-rt-impl.c $RT/wasm-rt-mem-impl.c $RT/wasm-rt-exceptions-impl.c
done
gcc -o host host.c -L. -la -lb -Wl,-rpath,'$ORIGIN'

./host b ; echo "exit=$?"
./host a ; echo "exit=$?"
```

## Actual result

```
$ ./host b
calling b_oob() ...
b_oob() trapped (as it should)
exit=0

$ ./host a
calling a_oob() ...
Aborted
exit=134
```

The fault in `b` (set up last) traps as expected. The same fault in `a` kills the process. `a` is exactly as correct as `b`; the only difference is the order of `*_setup()`.

## Expected result

Both calls trap and return to the caller, whatever the order in which the modules were set up.

## Why

The `SIGSEGV` handler of the process is one, and `os_install_signal_handler` in `wasm-rt-impl.c` replaces it without looking at the old one:

```c
if (sigaction(SIGSEGV, &sa, NULL) != 0 || sigaction(SIGBUS, &sa, NULL) != 0) {
```

Its handler calls `wasm_rt_trap`, which does `longjmp` to `g_wasm_rt_jmp_buf` **of its own copy**. Under gdb (`gdb -batch -ex "handle SIGSEGV nostop noprint pass" -ex run -ex bt --args ./host a`):

```
#4  abort ()
#5  wasm_rt_trap ()        from libb.so
#6  os_signal_handler ()   from libb.so
#7  <signal handler called>
#8  w2c_a_oob ()           from liba.so
#9  a_oob ()               from liba.so
#10 main ()
```

The fault is in the code of `a`, the handler is `b`'s, and `b`'s buffer was never set, so `WASM_RT_LONGJMP` of `wasm-rt.h` aborts:

```c
#define WASM_RT_LONGJMP(buf, val)                                   \
  /** Abort on failure as this may be called in the trap handler */ \
  if (!((buf).initialized))                                         \
    abort();                                                        \
```

## Second problem: the alternate stack cannot be had without installing the handler

An embedder that wants to own the signal handler (to chain several modules, or to keep its crash reporter) cannot tell the runtime "set up the alternate stack, but install no handler":

```sh
$ gcc -c -I$RT -DWASM_RT_SKIP_SIGNAL_RECOVERY=1 -DWASM_RT_STACK_EXHAUSTION_HANDLER=1 $RT/wasm-rt-impl.c -o /dev/null
wasm-rt.h:327:2: error: #error "WASM_RT_STACK_EXHAUSTION_HANDLER  can only be used if WASM_RT_INSTALL_SIGNAL_HANDLER is enabled"
```

`WASM_RT_SKIP_SIGNAL_RECOVERY` turns `WASM_RT_INSTALL_SIGNAL_HANDLER` off, and the handler for stack exhaustion (which needs the `sigaltstack` that `wasm_rt_init_thread` sets up)
requires it on.

## Suggested changes (either would do)

1. In `os_install_signal_handler` keep the previous action (`struct sigaction old`), and in the handler, when the fault is not in a call of this copy of the runtime
   (no valid unwind target: e.g. `g_wasm_rt_jmp_buf.initialized` is false, or a thread-local "inside a call" flag), call the old action instead of trapping. Restore it in `wasm_rt_free`.
2. Or a switch (say `WASM_RT_EMBEDDER_SIGNAL_HANDLER`) that sets up the alternate stack but installs no handler, with a documented function
   (`wasm_rt_handle_fault(const siginfo_t *)`) for the embedder's handler to call when the fault is in a call of the runtime.

We work around it today by redefining `sigaction` away while `wasm-rt-impl.c` is compiled and installing a chain of handlers ourselves (each one traps only when a call of
its own module is running and passes any other fault to the previous action). It works with two modules in both orders on Linux; I can turn it into a patch for
either option if you say which one you prefer.

Environment: WABT 1.0.42 (the code in `main` is the same), Linux x86-64, gcc 13.3.0 (Ubuntu 24.04). macOS has the same code with `SIGBUS`; Windows installs a vectored handler and is not affected.
