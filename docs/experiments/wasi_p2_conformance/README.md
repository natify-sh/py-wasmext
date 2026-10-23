# The host of WASI 0.2 against Wasmtime

The same script of operations is run by a guest in Wasmtime (a Rust component for `wasm32-wasip2`, run with `wasmtime-py`) and by the Python host of wasmext (`ours.py`, calling the functions of `wasi_p2_*` through a fake memory), and the lines they print are compared. The Python host is the reference for the C one: `tests/test_wasi_p2_*.py` keep the two equal.

    pip install wasmtime            # in the environment of the project
    rustup target add wasm32-wasip2
    (cd docs/experiments/wasi_p2_conformance/guest && cargo build --release --target wasm32-wasip2)
    python docs/experiments/wasi_p2_conformance/runner.py [script_fs.txt]

Not part of the tests: CI has neither Wasmtime nor the Rust target.

## wasi:filesystem (`script_fs.txt`, 262 operations)

What it covers: opening (every combination of path, open and descriptor flags), reading and writing (calls and streams), directories, symbolic links (followed or not, with a slash, dangling, loops), ways out of the preopen (`..`, absolute names, links that lead out), odd names (empty, `.`, `//`), `mkdir`/`rmdir`/`unlink`/`rename`/`link`/`symlink`/`readlink`, a read-only preopen, directories with and without `mutate-directory`, `set-size`, `sync`, `advise`, `is-same-object`, metadata hashes.

First run (2026-10-23): 39 of 236 operations differed. **Four of them were mistakes here and are fixed** (Python and C):

* `read` said `end-of-file` for any short read; Wasmtime says it only when nothing was read.
* An empty name was the directory itself; it is `no-entry` (POSIX), for every operation that takes a path.
* A slash after a link without `symlink-follow` was refused with `not-directory` (a safe answer found while comparing with uvwasi); POSIX and Wasmtime follow the link. The walk now follows it itself, below the base, so a link that leads out is `not-permitted`.
* `open` of a link with `directory` and no `symlink-follow` was `not-directory`; it is `loop`.

The rest is marked `#~` in the script with the reason (32 operations, all of them differences of choice, not of safety):

* **A read-only preopen:** Wasmtime says `not-permitted`, the WIT (and this host) `read-only`.
* **`mutate-directory`:** the WIT says `open-at` from a descriptor without it fails with `read-only` if it is asked to write or create; Wasmtime does not look at the flag (a directory opened with only `read` can still be changed through, and `get-flags` does not show `mutate-directory` at all). This host follows the WIT. *A guest that opens a directory without the flag and then changes it works in Wasmtime and fails here.*
* A FIFO is `fifo` here, `unknown` in Wasmtime.
* `link-at` with `symlink-follow`: Wasmtime says `invalid`, here it is done.
* A stream for writing on a descriptor that was opened without `write`: `bad-descriptor` at once here, the stream fails later in Wasmtime. The same for `set-size` and `write` on such a descriptor, and `read` of a directory (`is-directory` here, `bad-descriptor` there). A `blocking-read` of 0 bytes: an empty list here, `closed` there.
