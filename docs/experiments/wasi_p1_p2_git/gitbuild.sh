#!/bin/sh
# git 2.56.0 (git.git, no libgit2) for wasm32-wasip1, wasm32-wasip2 (p2) or wasm32-wasip2 with the sockets of wasi-libc (p2n), with wasi-sdk,
# after examples/git/real/build.sh of natify-sh/py-wasmhost (which uses `zig cc`). Usage: WORK=... SDK=... REAL=... gitbuild.sh p1|p2|p2n
#   WORK  a scratch directory that holds git.tar.xz (git-2.56.0.tar.xz, sha256 26c56c29...) and libgit2-sys-0.18.1+1.9.0 (its zlib) in orig/
#   SDK   the root of wasi-sdk 34.0
#   REAL  examples/git/real of py-wasmhost (wasi_compat.c, wasi_compat.h)
set -u
T=$1; TT=${T%n}; HERE=$(cd "$(dirname "$0")" && pwd)
: "${WORK:?}" "${SDK:?}" "${REAL:?}"
W=$WORK/gitw_$T; rm -rf "$W"; mkdir -p "$W"; cd "$W"
CC="$SDK/bin/clang --target=wasm32-wasi$TT"
tar xf "$WORK/git.tar.xz" -C "$W"; src=$W/git-2.56.0
# zlib: the copy that the libgit2-sys crate carries
mkdir -p zlib; z=$WORK/orig/libgit2-sys-0.18.1+1.9.0/libgit2/deps/zlib
cp "$z/zlib.h" "$z/zconf.h" zlib/; for f in "$z"/*.c; do $CC -Os -DHAVE_UNISTD_H -c "$f" -o "zlib/$(basename "$f" .c).o" 2>/dev/null; done; "$SDK/bin/llvm-ar" rcs zlib/libz.a zlib/*.o
# wasi_compat.c of py-wasmhost: the functions that wasi-libc does not have. For wasip2 the ones that wasi-libc has are taken out.
cp "$REAL/wasi_compat.c" compat.c
case $T in
  p2|p2n) sed -i '/^int dup(int fd)/d; /^int dup2(int a, int b)/d' compat.c ;;
esac
case $T in
  p2n) sed -i '/^int getaddrinfo(/d; /^void freeaddrinfo(/d; /^int getnameinfo(/,/^{ (void)a;/d; /^const char \*gai_strerror(/d; /^int socket(/d; /^int connect(/d; /^int setsockopt(/d' compat.c ;;
esac
$CC -Os -D_WASI_EMULATED_SIGNAL -I"$HERE/shim_$TT" -I"$HERE/shim" -I"$REAL" -c compat.c -o wasi_compat.o
# the two patches of the source of git
sed -i '/^void sanitize_stdfds(void)$/,/^{$/{s|^{$|{\n#ifdef __wasi__\n\treturn;\n#endif|}' "$src/setup.c"
sed -i '/^static int save_state(struct object_id \*stash)$/,/^{$/{s|^{$|{\n#ifdef __wasi__\n\treturn -1;\n#endif|}' "$src/builtin/merge.c"
cat > "$src/config.mak" <<EOF
CC = $CC
AR = $SDK/bin/llvm-ar
RANLIB = $SDK/bin/llvm-ranlib
uname_S = WASI
uname_M = wasm32
uname_O = WASI
NO_CURL = 1
NO_EXPAT = 1
NO_OPENSSL = 1
NO_GETTEXT = 1
NO_PERL = 1
NO_PYTHON = 1
NO_TCLTK = 1
NO_ICONV = 1
NO_PTHREADS = 1
NO_UNIX_SOCKETS = 1
NO_REGEX = 1
NO_SYS_POLL_H = 1
NO_INSTALL_HARDLINKS = 1
NO_MMAP = 1
NO_POSIX_GOODIES = 1
NO_RUST = 1
prefix = /usr
HAVE_SYSINFO =
NO_UNCOMPRESS2 =
SKIP_DASHED_BUILT_INS = 1
FSMONITOR_DAEMON_BACKEND =
FSMONITOR_OS_SETTINGS =
CFLAGS = -Os -include $REAL/wasi_compat.h -I$HERE/shim_$TT -I$HERE/shim -Dchmod=git_wasi_chmod -Dfchmod=git_wasi_fchmod -D_WASI_EMULATED_MMAN -D_WASI_EMULATED_SIGNAL -D_WASI_EMULATED_PROCESS_CLOCKS -D_WASI_EMULATED_GETPID -I$W/zlib -Wno-incompatible-pointer-types -Wno-implicit-function-declaration
LDFLAGS = -L$W/zlib -Wl,-z,stack-size=1048576
EXTLIBS = $W/wasi_compat.o -lwasi-emulated-mman -lwasi-emulated-signal -lwasi-emulated-process-clocks -lwasi-emulated-getpid
EOF
make -C "$src" -j"$(nproc)" git > make.log 2>&1; echo "make rc=$?"; ls -l "$src/git"
