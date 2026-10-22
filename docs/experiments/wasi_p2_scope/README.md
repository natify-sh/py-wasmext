# What a host of WASI 0.2 has to implement

`scope.py` counts the functions of the WIT of WASI 0.2 (tag `v0.2.12` of `WebAssembly/WASI`, stable items only) and sets them against the imports of four programs (git, git with sockets, hello, CPython with OpenSSL) and
against what the hosts in `examples/wasi2_unbundled` and `examples/wasi2_python` implement. The report is [../../wasi_p2_host_scope.md](../../wasi_p2_host_scope.md); `table.md` is the output.

```sh
git clone --depth 1 --branch v0.2.12 https://github.com/WebAssembly/WASI wasi
mkdir -p witroot/wit/deps && cp wasi/proposals/http/wit/*.wit witroot/wit/       # http imports the others
for p in cli clocks filesystem io random sockets; do mkdir witroot/wit/deps/$p; cp wasi/proposals/$p/wit/*.wit witroot/wit/deps/$p/; done
wasm-tools component wit witroot/wit --json > stable.json                         # --all-features adds 4 unstable functions
python scope.py stable.json git.component.wasm git_p2_net.component.wasm hello.component.wasm cpy_p2s.wasm > table.md
```

The programs are those of [../wasi_p1_p2_git/](../wasi_p1_p2_git/) and [../wasi_p1_p2_cpython/](../wasi_p1_p2_cpython/) (not kept in the repository). "Seen" is a union over libc-based C programs only.
