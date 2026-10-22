#!/bin/sh
# CPython 3.15 (commit 1c6794e of python/cpython, as py-wasmhost pins it) for wasm32-wasip1 and wasm32-wasip2 with the build that CPython ships (Platforms/WASI) and wasi-sdk 34.
# Usage: SDK=... CHECKOUT=... WORK=... ZLIB_SRC=... cpbuild.sh native | zlib p1|p2 | host p1|p2 [extra configure arguments]
set -u
: "${SDK:?}" "${CHECKOUT:?}" "${WORK:?}" "${ZLIB_SRC:?}"
cmd=$1; shift
LOGS=$WORK/logs; mkdir -p "$LOGS/native" "$LOGS/host-p1" "$LOGS/host-p2"
case $cmd in
  native)  # the build Python that the cross build needs
    cd "$CHECKOUT" && python3 Platforms/WASI build-python --quiet --logdir "$LOGS/native" ;;
  zlib)    # wasi-sdk has no zlib: the sources of the libgit2-sys crate (zlib 1.3.x), compiled by hand
    t=$1; out=$WORK/zlib-$t; rm -rf "$out"; mkdir -p "$out/include" "$out/lib" "$out/obj"
    for c in $(cd "$ZLIB_SRC" && ls *.c | sed "s/\.c$//"); do
      "$SDK/bin/clang" --target=wasm32-wasi$t -O2 -DHAVE_UNISTD_H -D_LARGEFILE64_SOURCE=1 -c "$ZLIB_SRC/$c.c" -o "$out/obj/$c.o" || exit 1
    done
    "$SDK/bin/llvm-ar" rcs "$out/lib/libz.a" "$out"/obj/*.o; cp "$ZLIB_SRC/zlib.h" "$ZLIB_SRC/zconf.h" "$out/include/" ;;
  host)
    t=$1; shift
    cd "$CHECKOUT" && python3 Platforms/WASI build-host --quiet --logdir "$LOGS/host-$t" --host-triple wasm32-wasi$t --wasi-sdk "$SDK" --host-runner true \
      ZLIB_CFLAGS="-I$WORK/zlib-$t/include" ZLIB_LIBS="-L$WORK/zlib-$t/lib -lz" "$@" ;;
esac
