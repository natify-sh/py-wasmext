#!/bin/sh
# usage: run.sh BIN RT   (BIN: the directory with wat2wasm and wasm2c; RT: the wasm2c/ directory of the sources of WABT). Linux, gcc.
# Two shared libraries, each with its own copy of the runtime of wasm2c; the one set up last owns the SIGSEGV handler, and a fault in the other aborts the process.
# The issue draft that goes with it: ../../wabt_issue_drafts/signal_handler.md (not opened yet).
set -e
BIN=$1; RT=$2
$BIN/wat2wasm m.wat -o m.wasm
for n in a b; do
  $BIN/wasm2c m.wasm -o $n.c --module-name=$n
  sed "s/NAME/$n/g" lib.c > lib_$n.c
  gcc -O1 -shared -fPIC -fvisibility=hidden -I$RT -I. -o lib$n.so lib_$n.c $n.c $RT/wasm-rt-impl.c $RT/wasm-rt-mem-impl.c $RT/wasm-rt-exceptions-impl.c
done
gcc -o host host.c -L. -la -lb -Wl,-rpath,'$ORIGIN'
./host b; echo "exit=$?"     # b was set up last: traps as it should
./host a; echo "exit=$?"     # a: Aborted (exit 134)
