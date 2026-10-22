#!/bin/sh
# OpenSSL 3.5.0 for wasm32-wasip2 with wasi-sdk 34 (static libssl.a, libcrypto.a), then CPython 3.15 with `_ssl` and `_hashlib`.
# Usage: SDK=... SRC=<openssl-3.5.0 tree> PREFIX=... opensslbuild.sh openssl | cpython-flags
set -eu
: "${SDK:?}" "${SRC:?}" "${PREFIX:?}"
case $1 in
  openssl)
    cd "$SRC"; export CC="$SDK/bin/clang --target=wasm32-wasip2" AR=$SDK/bin/llvm-ar RANLIB=$SDK/bin/llvm-ranlib
    # no-quic: ssl/rio/rio_notifier.c needs socketpair. no-threads: crypto/thread/arch/thread_posix.c needs pthread_exit (wasi-libc has none).
    # -DOPENSSL_NO_UNIX_SOCK: wasi-libc's sockaddr_un has no sun_path.
    ./Configure linux-generic32 no-threads no-asm no-shared no-dso no-apps no-tests no-docs no-afalgeng no-ui-console no-secure-memory no-engine no-async no-ktls no-quic \
      -DOPENSSL_NO_UNIX_SOCK -D_WASI_EMULATED_SIGNAL -D_WASI_EMULATED_PROCESS_CLOCKS -D_WASI_EMULATED_MMAN --prefix="$PREFIX" --openssldir="$PREFIX/ssl"
    make -j4 build_libs && make install_dev
    # WORKAROUND: CPython's _ssl.c and _hashopenssl.c refuse OpenSSL without OPENSSL_THREADS. WASI has no threads, so the macro is only defined, not true.
    sed -i '0,/^#ifndef OPENSSL_CONFIGURATION_H/s//#define OPENSSL_THREADS 1\n#ifndef OPENSSL_CONFIGURATION_H/' "$PREFIX/include/openssl/configuration.h" ;;
  cpython-flags)
    echo "build-host ... -- CC=... CPP=... CXX=... ZLIB_CFLAGS=... ZLIB_LIBS=... --with-openssl=$PREFIX   (as cpbuild.sh host p2; --clean the tree if it was configured before)" ;;
esac
