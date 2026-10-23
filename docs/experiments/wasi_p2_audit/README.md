# Does the host of WASI 0.2 match the WIT?

Two scripts that read the WIT of `v0.2.12` (as in [../wasi_p2_scope/README.md](../wasi_p2_scope/README.md): `wasm-tools component wit WITROOT --json > stable.json`, run from this directory) and check `wasmext.p2` and `c/p2/`:

- `audit_sigs.py`: for every import of cli, clocks, filesystem, io, random, sockets and http (the command world, 137, and http, 63; `incoming-handler` is an export and is left out), the number of flat parameters by the rules of the Canonical ABI (a pointer for the result when it is not one flat value), whether the function returns a value, and that the Python and the C function exist with the same number of parameters. Result at the time of writing: 200 checked (functions and drops), 0 problems.
- `audit_http_cases.py`: the table of the payloads of the 39 cases of `wasi:http` `error-code` (`CASES` in `wasi_p2_http.py`) against the WIT: names, order, shape (0 different).
- `audit_layout.py`: size, alignment and the offsets of the payloads of every result type, to be read against the layouts written in `wasi_p2_io.py` / `wasi_p2_filesystem.py` (all agree).

What the scripts do not check is the behaviour; that was read against the comments of the WIT by hand (2026-10-23), and five differences were found and fixed: a failed stream is closed afterwards; `read-only` (not `not-permitted`) when `mutate-directory` is missing; absolute targets of links (`readlink-at`, `symlink-at`); `metadata-hash` follows the size and the modification time; `unlink-file-at` of a directory is `is-directory` on every system.
