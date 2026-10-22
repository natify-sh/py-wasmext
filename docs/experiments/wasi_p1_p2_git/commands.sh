# The commands of the study in docs/wasi_p1_p2_host_requirements.md, in the order of the report. Not a script to run as it is: $SDK is wasi-sdk 34.0,
# $WORK a scratch directory, $WH a checkout of natify-sh/py-wasmhost, $SHIM this directory. Tools: wasm-tools 1.262.0, meld 0.64.0 (built from source), wasmext.

## sources (the checksums are those that py-wasmhost pins)
curl -fsSL -o $WORK/git.tar.xz https://mirrors.edge.kernel.org/pub/software/scm/git/git-2.56.0.tar.xz               # sha256 26c56c296b38...
curl -fsSL -o $WORK/crate.tgz  "https://static.crates.io/crates/libgit2-sys/libgit2-sys-0.18.1+1.9.0.crate"       # sha256 e1dcb20f84ff...
mkdir $WORK/orig && tar xzf $WORK/crate.tgz -C $WORK/orig
src=$WORK/orig/libgit2-sys-0.18.1+1.9.0/libgit2

## libgit2 + lg2.c (examples/git of py-wasmhost): the same sources for wasip1 and wasip2. t is p1 or p2.
cp $WH/examples/git/stubs/process.c $src/src/util/unix/process.c          # no processes: a patch on both
# socket.c: wasip1 does not compile libgit2's own (no netdb.h), so py-wasmhost replaces it with a bridge to the host (stubs/socket.c, four imports of
# `wasmhost_net`); for the study of the build without a network the bridge was made to fail without imports (socket_nonet.c here, a copy of stubs/socket.c with
# its four imports written as functions that fail), and was put in place of streams/socket.c for both targets. On wasip2 the original compiles as it is.
cp $SHIM/../socket_nonet.c $src/src/libgit2/streams/socket.c               # only for the builds 'without a network'
flags="-I$SHIM -I$SHIM/../shim_p1 -D_WASI_EMULATED_MMAN -D_WASI_EMULATED_SIGNAL -D_WASI_EMULATED_PROCESS_CLOCKS -D_WASI_EMULATED_GETPID -Wno-incompatible-pointer-types"
cmake -S $src -B cmake_$t -G Ninja -DCMAKE_TOOLCHAIN_FILE=$SDK/share/cmake/wasi-sdk-$t.cmake -DWASI_SDK_PREFIX=$SDK \
  -DCMAKE_BUILD_TYPE=MinSizeRel -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTS=OFF -DBUILD_CLI=OFF -DBUILD_EXAMPLES=OFF -DUSE_THREADS=OFF \
  -DUSE_HTTPS=OFF -DUSE_SSH=OFF -DUSE_SHA1=CollisionDetection -DUSE_SHA256=builtin -DREGEX_BACKEND=builtin \
  -DUSE_HTTP_PARSER=builtin -DUSE_NTLMCLIENT=OFF -DUSE_GSSAPI=OFF -DUSE_NSEC=OFF -DUSE_ICONV=OFF -DCMAKE_C_FLAGS="$flags"
ninja -C cmake_$t
# the stack: 64 KiB by default; libgit2 traps (out of bounds) while it creates a repository, so 1 MiB (zig gives more by default)
$SDK/bin/clang --target=wasm32-wasi$t -Os $flags -I$src/include $WH/examples/git/lg2.c $WH/examples/git/compat.c cmake_$t/libgit2.a \
  -lwasi-emulated-mman -lwasi-emulated-signal -lwasi-emulated-process-clocks -lwasi-emulated-getpid -Wl,-z,stack-size=1048576 -o git_$t.wasm
# wasip2 with libgit2's own sockets (nothing replaced): lg2.c wants a TLS stream from the bridge, which does not exist, so tls_none.c answers "none"
$SDK/bin/clang --target=wasm32-wasip2 -Os $flags -I$src/include $WH/examples/git/lg2.c $WH/examples/git/compat.c $SHIM/../tls_none.c \
  cmake_p2_net/libgit2.a -lwasi-emulated-mman -lwasi-emulated-signal -lwasi-emulated-process-clocks -lwasi-emulated-getpid \
  -Wl,-z,stack-size=1048576 -o git_p2_net.component.wasm      # cmake_p2_net: libgit2 built as above, without the replaced socket.c

## git.git 2.56.0: gitbuild.sh p1 | p2 | p2n  (WORK, SDK, REAL=$WH/examples/git/real)
./gitbuild.sh p1; ./gitbuild.sh p2; ./gitbuild.sh p2n

## the ways of using a wasip2 component
wasm-tools component unbundle x.wasm --threshold 0 --module-dir unb -o unb/rest.wasm     # the default threshold (10240 bytes) leaves small modules inside rest.wasm
meld fuse x.wasm -o x.fused.wasm --exports world --emit-import-map x.imports.json     # without --exports world the fused module also exports its tables ('0'..'34')

## wasmext
wasmext inspect x.wasm                       # imports, exports, `wasi:` line
wasmext natify -i -b -q x.wasm               # the extension; WASI 0.1 is inside the module, WASI 0.2 is for the host
