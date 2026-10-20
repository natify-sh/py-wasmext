# Design notes

How the parts of wasmext were designed and built: linking instances, WASI, "C first" (the layers, the glue as files, the
shared library, the executable), the audits, and the decisions. This is the reasoning and the history; **what is true now, and
what is open, is in [FEATURES.md](FEATURES.md)**, and where the build puts its files is in [build_model.md](build_model.md).
When a section here and the code differ, the code wins.

## Design: linking instances (globals, functions and memories are built; tables are not)

The goal is the "shared objects" of the plan: an instance uses a global, a memory, a table or a function of another instance.
wasmext stays native: no `Global`/`Memory`/`Table` classes copied from the JavaScript API (as `wasmhost` has, because there an
engine owns the objects), but the exports of one instance given as the imports of another.

```python
a = A.Instance()
b = B.Instance({"env": a})  # imports of module "env" are taken, by name, from the exports of a
```

**What wasm2c gives.** The C of a module that imports a global, a memory or a table keeps a *pointer* to it (`u32 *w2c_env_g`,
`wasm_rt_memory_t *w2c_env_mem`, `wasm_rt_funcref_table_t *w2c_env_tab`), taken at instantiation from the accessors
`w2c_env_g(struct w2c_env *)` that the host defines; an exported one has the same shape (`u32 *w2c_m_eg(w2c_m *)`,
`wasm_rt_memory_t *w2c_m_em(w2c_m *)`, `wasm_rt_funcref_table_t *w2c_m_et(w2c_m *)`). So linking is handing the pointer
of the exporter to the importer: one value, one memory, one table, no copy, no Python in between. An imported function is
`w2c_env_f(struct w2c_env *, args)`: the glue can call the exported function of the other module itself (its instance pointer is
the first argument) instead of a Python callable.

**How the imports are given (decided).** A shelf is a dict, and a value in it can be a reference to an export of another instance.
There are two kinds of access on an instance, with different jobs:

| | | |
| --- | --- | --- |
| attributes | **use** the module from Python | `a.add(2, 3)` calls; `a.counter` is the number, `a.counter = 5` sets it; `a.mem` is a memoryview |
| items | **link** it to another module | `a["counter"]` is the reference to the export; `a.__exports__` is the dict of all of them |

```python
B.Instance({"env": a})  # a shelf from an instance: all of it
B.Instance({"env": {"log": print}})  # a dict: by keys, as now
B.Instance({"env": {**a.__exports__, "log": print}})  # everything of a, and log from Python (the later key wins)
B.Instance({"env": {"counter": a["counter"], "log": print}})  # one export of a, and log from Python
```

There is no `export()` and no `keys()` on the instance: the instance has no names of its own, only the double-underscore ones
(`__exports__`, `__getitem__`, ...), and an export called like that is not an attribute (it is in `__exports__`), so a name of an
export never clashes with one of the instance. `**a` does not work (it needs `keys()`), `**a.__exports__` does. Write the dict as a
literal or `dict(a.__exports__, log=print)`: `dict(**a.__exports__, log=print)` is a `TypeError` of Python (a duplicate keyword).
Almost every compiler puts all its imports on one shelf, `env`, the host functions (print, clock) and the ones another module could
give, so the dict forms are the common ones for real modules. Beware that `{"env": a}` matches by name: if both `a` and the host
could give `log`, `a` wins silently when the types agree; the dict with the explicit key shows what is meant.
Left out for now: a list of sources (`{"env": [a, {"log": print}]}`); a wrapper object for a function that is both callable and a
reference (it cannot be done for a global or a memory, whose attribute has to be the value, and costs a type and a cache); instead,
when functions are linked, a bound method of an instance (`{"add": a.add}`) can be accepted as the reference at no cost on a call.
Names of exports that the module does not import are ignored. Built: globals (also immutable ones), functions, memories, `a["name"]`,
`__exports__` and the shelf from an instance. Tables are not (they first have to be exposed as an object).

**Recognising an instance of another extension.** The types are not the same objects in two extensions, so `isinstance` cannot
tell. What `instance['name']` and `instance.__exports__` hold is a capsule (a `PyCapsule`, usable in the limited API) named
`wasmext.export.v1`, one for each export, that points to a record `wasmext_export`: `size`, `version` (1), `kind` (function, table,
memory, global), `type`, `flags`, the owner (the instance, which a reader that keeps the address keeps alive) and `address`; for a
function also the `instance` pointer and the `signature` (`"ii>i"`: `i j f d o`); and `runtime`, the fingerprint of the layout of the structs of the wasm2c runtime. For a global `type` is the value type of the binary
format (`0x7F` is i32) and bit 0 of `flags` says it is mutable; for a memory `type` is `sizeof(wasm_rt_memory_t)` and `flags` has memory64
(bit 1) and guard pages (bit 2). A function is called as `result f(void *instance, parameters..., int *trapped)`, which catches the
trap with the jump buffer of the exporter, so each extension handles its own traps. The format is a contract between versions of wasmext,
so it is versioned from the first day; an unknown version, or a `size` smaller than the reader knows, is a `LinkError`, not a guess.

**Keeping the contract still.** Changing it means a new `v2` and every extension built before it fails to link with the new
ones, so it is made to change rarely: the record begins with its own `size`, and new fields are only appended (a reader checks
`size` before it reads one: an old reader ignores the fields it does not know, and a new reader refuses a record smaller than its own
struct with a `LinkError`, as the code does today; it does not guess what an old record would have held); the entries are a
fixed-size record with a `kind` and room for flags; the pointers are those of wasm2c (`u32 *`, `wasm_rt_memory_t *`,
`wasm_rt_funcref_table_t *`), so wasmext adds nothing of its own to what must stay the same. The name `wasmext.export.v1`
changes only if a field is *removed or changes meaning*, which should never be needed.

**Checks, all at instantiation, all `LinkError`**: the export exists; it has the kind the import asks for (a function is not a
global); the types are equal (`i32` ≠ `i64`, mutable ≠ immutable, the signature of a function); for a memory, the limits of the
import are satisfied (initial and maximum pages, memory64 equal). For a table (not built) the element type and limits would be checked too.

**Lifetime.** The importer holds a strong reference to the exporter, so the pointers stay valid as long as it lives. A cycle
(a imports from b and b from a) is not possible at instantiation, because an instance has to exist before it is given; an
instance takes part in the cycle collector already, and the reference is visited in `tp_traverse` and cleared in `tp_clear`.
`wasm2c_<m>_free` of the exporter must not run while an importer lives: guaranteed by the reference.

**Memory.** The memory object is the same, so `a.mem` and `b.mem` are `memoryview`s of the same bytes. A `grow` by either is seen by
both (the struct is shared); a view taken before the grow is the old size, as it is today (a new one after).

**Functions between instances.** The glue of the importer calls `w2c_<provider>_<name>` of the other extension through the table of
the capsule, so the traps cross: a trap in the callee unwinds to the call from Python, as when a Python callable calls back. The
jump buffer is per thread and the call goes on the same stack, so the existing `ENTER_WASM`/save-and-restore applies; a trap in the callee comes
out as the `Trap` of its module through the caller, and both instances go on (`test_instances_call_each_others_functions_directly`).

**Not covered (and why that is fine for now)**: a global, memory or table made by the host with no module behind it (a small
object would be needed; postponed until somebody needs it); `externref` tables; threads and `shared` memory (the pointer is shared,
but not made atomic: that is plan item 4 and changes the layout, so this design must not rely on plain reads of a mutable global
once threads exist); instances from different wasmext *builds* with different wasm2c runtimes (the structs of `wasm-rt.h` have to
match: the record has a fingerprint of their layout, `runtime` (the sizes and offsets of `wasm_rt_memory_t` and the size of the table struct), and an import
from an extension with another one is a `LinkError`: `test_an_export_of_another_wasm2c_runtime_is_not_linked`). It is the layout that is compared, not the version of WABT.

**Order**: 1. imported mutable globals from an exporting instance (smallest: a pointer and a type check; also removes the "refused
when the extension is made" for them); 2. memories; 3. functions: these three are built, in this order; 4. tables: not built.

**Decided**: the forms above; the format of the link table (capsule) is private, documented and
versioned (not a promise to others) until a second user of it exists.

## Design: WASI

**Decided.** WASI is part of wasmext and is compiled into the native module; a built module needs nothing at run time (not wasmext
either), so a shared library that modules call into was rejected. The code is hand-written C, **header only**, one header for each interface the module
imports: `wasi_preview1.h` for `wasi_snapshot_preview1` and `wasi_unstable.h` for `wasi_unstable` (the first snapshot,
"preview0"), which share `wasi_core.h`. The headers are copied into `build/wasmext/<module name>/` and included by the glue of the module (both, if it
imports both), so there is no second source file to build. Its functions are `static inline`: the glue names the ones the module imports, and the compiler drops
the others, so a module has only the calls it imports. It is not generated each time, so it can be read, tested and fixed as ordinary C.
`wasi_unstable` is not folded into `wasi_preview1`: the day a call differs between them, it gets its own function there.
WASI 0.2 and 0.3 are not another header of this kind: see "WASI 0.2 and 0.3" below. A call that WASI does not have, or that
a module imports with another signature, is refused when the glue is made (`GenError`).

**Portability: direct where it is the same, through `Python.h` where it is not.** A call is made in plain C when the C library behaves the
same on POSIX and on Windows (the CRT), with no interpreter in between. A call that can differ on Windows (non-POSIX) goes through
CPython instead (the `os`, `io`, `time` and `sys` modules, called from C with the limited API, so an abi3 module can use it), and then
differs only where Python itself differs. The rule is applied call by call; the table is what was built, and the official tests of WASI
run on it in CI (Linux both ways, macOS, Windows):

| Way | Calls | Why |
| --- | --- | --- |
| direct | `args_*`, `environ_*`, `sched_yield`, `fd_prestat_*`, the bookkeeping of descriptors, `fd_seek`/`fd_tell`, `fd_read`/`fd_write` on the descriptors it opened | data of the instance, or the same call on both |
| plain C (was through Python until the decision on `wasi=`) | `random_get`, `clock_*`, the sleep of `poll_oneoff` | the source differs between systems and none of it needs the interpreter: `/dev/urandom` (`arc4random_buf` on macOS, `BCryptGenRandom` on Windows), `clock_gettime` (`QueryPerformanceCounter`, `GetSystemTimePreciseAsFileTime`, `GetProcessTimes`, `GetThreadTimes` on Windows), `nanosleep` (`Sleep`) in slices of 100 ms with the interpreter released, so that Ctrl+C is seen. A function the caller gives (`clock`, `random`) replaces them |
| directly, where the system has `openat` (decided on a measurement, see below) | `path_open`, `path_filestat_get`, `fd_filestat_get`, `fd_readdir` | a directory is an open descriptor and a path is walked from it one name at a time; no interpreter |
| through Python (Windows; and anywhere with `-DWASMEXT_WASI_PYTHON_FS=1`, for the tests) | the same calls, and the ones of the later stages | Windows has no `openat`; it cannot open a directory with `open`, has its own `stat` (no inode), `FindFirstFile` for a listing, other rules for renaming over a file; symbolic links need a privilege |
| through Python (decided) | `fd_read`/`fd_write` on the standard streams | direct writes to descriptors 1 and 2 bypass the buffer of `sys.stdout` (the order against Python's `print`, a capture in a notebook or a test), so by default they go to `sys.stdout.buffer` after a flush of `sys.stdout` |

**What it covers.** The 46 functions of the specification (`wasi_snapshot_preview1.witx`, the branch `wasi-0.1` of WebAssembly/WASI;
the files are in `tests/data/wasi/` of py-wasmhost, with their licence): arguments, environment, clocks, `random_get`,
`proc_exit`, `sched_yield`, `poll_oneoff`, the `fd_*` calls, the `path_*` calls. Sockets, signals and threads answer as the
specification allows (`ENOTSOCK`, `ENOSYS`). The first snapshot, `wasi_unstable` (what `lua.wasm` imports), has the same
functions but `sock_accept`, and four differences in what it reads and writes: the order of `whence` (cur, end, set), one right less,
`filestat` with a 32-bit link count (which moves its fields), and a clock subscription with an extra `identifier` (56 bytes). So the
two files differ in the few calls that touch those (`fd_seek`, `fd_fdstat_get`, `fd_filestat_get`, `path_filestat_get`, `poll_oneoff`);
the rest is common. A private header holds the common part, which both headers include, so that they cannot drift apart (`wasi_core.h`); the four that differ have a
function of their own in `wasi_unstable.h` (`fd_seek`, `fd_filestat_get`, `path_filestat_get`, `poll_oneoff`), and the rest serves both snapshots. A module gets only the functions it imports, so a module
without WASI contains none of it. The state (file descriptors, preopens) is in the instance, not in globals.

**Staged (all three built).** First what is the same everywhere: standard streams, arguments, environment, clocks, `random_get`, `proc_exit`. Then
files and directories (`fd_*`, `path_*`) with preopens that confine the program to a directory: reading, then writing and creating. Last the links, `pread`/`pwrite`,
renaming and `poll_oneoff`.

**Reference for behaviour.** The witx files give the names and signatures; the oracle is the official test suite (below), not `wasmhost.wasi.preview1`
(plain Python, MIT), which was meant to be run beside it and was not. Its code is not copied: this is written from the specification.

**Decided (the first version).**
- Configuration is a keyword of the instance, `Instance(imports, wasi={"args": [...], "env": {...}, "preopens": {"/": "dir"},
  "stdin": ..., "stdout": ..., "stderr": ...})`.
- Standard streams go to `sys.stdin.buffer`, `sys.stdout.buffer` and `sys.stderr.buffer` by default, so that capturing in a notebook or
  a test works, and an object with `write(bytes)` replaces one.
- `proc_exit(n)` is an exception (`WasiExit`, carrying the code) out of the call that led to it; `proc_raise(signal)` is `WasiSignal` (`.signal`, `.name`); both are a `WasiTerminated`. The program is over: see "The end of a program" in "Decisions".
- The command `_start` is called as an export, as any other (no `run()` helper in the first version).
- Test modules: `lua.wasm` (wasi_unstable, 19 imports) first, then `coreutils.wasm` (preview1, 32 imports, 10.8 MB, which makes a very large
  C file and a long build). Both were built and run: `lua.wasm` is `examples/lua`, `coreutils.wasm` was run by hand (built in 16 files).

**Stages 1, 2 and 3 (built).** `src/wasmext/c/wasi_core.h` with `wasi_preview1.h` and `wasi_unstable.h`, copied beside the C of a module that
imports WASI and included by its glue (the glue calls the functions directly, through the slots that linking instances uses). The calls
that work: `args_*`, `environ_*`, `clock_res_get`, `clock_time_get`, `random_get`, `sched_yield`, `proc_exit` (raises the module's `WasiExit`,
`.code`), the standard streams (`fd_read` on stdin, `fd_write` on stdout and stderr), and for files and directories: preopens
(`wasi={"preopens": {name: directory}, "readonly": ...}`), `path_open` (reading, creating, truncating, writing, append), `fd_read`, `fd_write`, `fd_seek`, `fd_tell`, `fd_close`, `fd_renumber`,
`fd_advise`, `fd_fdstat_get`, `fd_filestat_get`, `path_filestat_get`, `fd_readdir`, `fd_prestat_get`, `fd_prestat_dir_name`, and (stage 2) `fd_sync`, `fd_datasync`,
`fd_allocate`, `fd_filestat_set_size`, `fd_filestat_set_times`, `path_filestat_set_times`, `fd_fdstat_set_flags`, `fd_fdstat_set_rights` (rights can only
be given up), `path_create_directory`, `path_remove_directory`, `path_unlink_file`, and (stage 3) `fd_pread`, `fd_pwrite`, `path_rename`, `path_link`, `path_symlink`, `path_readlink`, `poll_oneoff`, and (stage 4) `proc_raise`: 42 of the 46 calls
and, with the answers the specification allows, all of them: the four `sock_*` are `ENOTSOCK` (`EBADF` for no such descriptor), as in
wasmhost. `poll_oneoff` sleeps in C (the interpreter released, a signal seen every 100 ms) until the first clock; descriptors of files, directories and standard streams are always ready;
the first snapshot has its own (a clock subscription with an identifier, 56 bytes). A symbolic link is made with a relative target only (an absolute one is
`ENOTCAPABLE`), and one that points out is not followed. `pread`/`pwrite` use the system calls; Windows seeks, does it and seeks back; `rename` replaces
a file in the way (`os.replace` on the Python path). On POSIX these go straight to the system (`write`, `mkdirat`, `unlinkat`, `utimensat`, ...) after the same walk that confines a path. Rights are kept per descriptor (`readonly` takes the
mutating ones away), and a directory descriptor is a capability for that directory: `..` out of it, an absolute name, or a link that
leads out are `ENOTCAPABLE` (an absolute link inside is refused too, as in cap-std). Both snapshots are served (`sock_accept` is not a call of the first:
`GenError`); the first has its own `fd_seek` (another order of `whence`) and `fd_filestat_get`/`path_filestat_get` (56 bytes). `Instance()` needs no
imports; `wasi={...}` takes args, env, stdin, stdout, stderr, preopens, readonly. What the caller gives as an import wins, call by call.
**The official tests.** The precompiled programs of [WebAssembly/wasi-testsuite](https://github.com/WebAssembly/wasi-testsuite) (`prod/testsuite-base`, commit
`d552798`, WASI 0.1: AssemblyScript, C and Rust, 72 programs; the 55 of WASI 0.3 are skipped) run on wasmext: `tests/wasi_testsuite/adapter.py` is the
adapter for the runner of the suite, `run_wasmext.py` builds one program into a native extension (without optimizing) and runs it, and `prebuild.py` builds all
of them at the same time first (the runner kills a program after its timeout, and the first run of a program is a build). CI (`.github/workflows/wasi-testsuite.yml`)
runs it with `wasmext` on Python 3.11 and the runner on 3.12 (it needs it): **all 72 pass** on Linux (both ways of reaching files: `openat`, and Python, as a
fourth job), macOS (the suite told to expect the errors of macOS, `ERRNO_MODE_MACOS`) and Windows. On Linux the suite is told `ERRNO_MODE_UNIX`; on Windows it
is not told `ERRNO_MODE_WINDOWS` (that mode asks for the errors of a system that is not POSIX, where wasmext gives those of POSIX, so any error of the systems is
taken) but `NO_RENAME_DIR_TO_EMPTY_DIR`. One test is expected to fail on Windows when the files go through Python (`expectations-windows-python-fs.toml`): `symlink_filestat`, because Python before 3.13 cannot set the
times of a link itself.

What they found, that our tests had not: the same function imported twice (AssemblyScript; a duplicate in the glue); a directory opened with all the rights of its
preopen (a retry as a directory on `EISDIR`); the rights of an opened directory (no seek); a trailing slash (`file/` is `ENOTDIR`, and a name to be made that has one is
`EEXIST`, `ENOTDIR` or `ENOENT`); `fd_renumber` of the standard streams; `pwrite` on a file opened for writing only (no `fd_seek` is asked for); and, on Windows (the Python way),
`os.utime` of a file by its descriptor (it has none: the path is kept), the inode of `.` and `..` in a listing, no `O_NOFOLLOW` (a link is not opened without following it: `ELOOP`, checked by hand), links made with `/`,
`O_APPEND` (it cannot be taken off again: `fd_write` seeks to the end), `os.link` that does not follow a link, and the times of a link (`follow_symlinks=False` only for a link).
It also found that the runner kills a program after 5 s unless the adapter says more, and that what a killed program started goes on on Windows and held the runner for 30 minutes.
Not built: threads; sockets and the clocks of the process and the thread in `poll_oneoff` are decided against for now (see "Decisions"). Tests: `tests/test_wasi.py` and `tests/test_wasi_fs.py` (through `build_extension`, not on
Windows; the file tests are run for both ways of reaching the file system), `test_a_wasi_module_is_built_with_the_wasi_header_of_wasmext`
and `test_wasi_files_work_on_every_platform_of_ci` (the whole path, every platform of CI). `lua.wasm` (imports `wasi_unstable`) is built and run by `examples/lua` (its tests, and the wheels of CI).

**The cost of a call, measured** (Linux x86-64, Python 3.11, gcc -O2, medians; a loop in WebAssembly that makes the call). First version,
where every path went through Python (`os.stat`, `os.path.realpath` for the check of the limits): `path_filestat_get` 17.5 us, `path_open` +
`fd_close` 18.9 us, `fd_readdir` of 101 names 224 us; 13 us of the first were the `realpath` of the check alone. After the move to `openat`:
0.87 us, 1.6 us and 30 us (the floor in C for the listing is about 18 us). `fd_read`/`fd_seek` on a file (direct since the beginning) 0.1 us;
`clock_time_get` (measured when it went through Python, `time.time_ns`; it is plain C now and was not measured again) 0.14 us; a call of WebAssembly into a C function 3 ns. The way through Python costs 0.1 to 0.9 us
over the system call itself for a simple call; that was the reason to keep the clocks and the random bytes there, until the decision that what needs no Python is C. (An earlier figure of "190 times"
for the listing came from a wrong baseline and is withdrawn.) Windows is on the Python way and was not measured; a native path for it (`NtCreateFile` relative to a directory handle, as cap-std does) is possible, would be 600 to 900 lines of C that can be tried only in CI, and is not written.

### What the C layer does by itself, and what waits for `wasi=`

How it is now (after the decision "The configuration of WASI" below). "Plain C" needs no interpreter, "C through `Python.h`" calls it; a key of
`wasi=` that is absent has the default of this table, `None` is nothing, and any part can be replaced.

| Part of the program's world | The default, and who gives it | `wasi=` | Built |
| --- | --- | --- | --- |
| Arguments (`args_*`) | `[the name of the program]`; plain C | `args` (`None`: none) | yes |
| Environment (`environ_*`) | empty; plain C | `env` | yes |
| `stdin`, `stdout`, `stderr` | `sys.stdin`, `sys.stdout`, `sys.stderr` of the moment; C through `Python.h`, in the binary layer, after a flush of the text layer | `stdin`, `stdout`, `stderr` (`None`: an empty input, an output thrown away; a text stream given explicitly works the same way) | yes |
| Clocks (`clock_*`) | those of the system; plain C | `clock` (a function: id -> nanoseconds; no `None`) | yes |
| Random bytes (`random_get`) | those of the system; plain C | `random` (a function: how many -> bytes; no `None`) | yes |
| Sleeping in `poll_oneoff` | the interpreter released, slices of 100 ms; plain C | (the call) | yes |
| `proc_exit` | raises `WasiExit` with the code; C through `Python.h`. The program is over: its descriptors are closed at once, a call after it is `WasiTerminated` | (the call) | yes |
| `proc_raise` | `WasiSignal` (`.signal`, `.name`); a signal that nothing ends (none, the child, continue, the stops, urgent data, the window size) is a success and the program goes on | (the call) | yes |
| Files and directories | none (the POSIX walker is plain C, on Windows C through `Python.h`) | `preopens`, `readonly` | yes |
| Sockets | none (`sock_*` give `ENOTSOCK`) | (postponed, see "Decisions") | no |

Whatever is not in `wasi=` can be replaced call by call through `imports`.

## Design: C first, the seams (stage 1 of item 10)

Written from a reading of `wasi_common.h` (2860 lines; the name it had before stage 2 cut it into `wasi_core.h` and `wasi_python.h`) and `_gen.py`; nothing here is built yet. The figure "49 of 135 functions mention
Python" came from a rough search; the groups below are what the reading found and are the figures to trust.

### Where Python is in the core of WASI today

| Group | Functions | Why it needs Python now | Where it goes |
| --- | --- | --- | --- |
| Configuration | `wasi_pack_strings`, `wasi_config_*`, `wasi_apply_option`, `wasi_setup_preopens`, `wasmext_wasi_new` | reads the dict `wasi=` (`os.path.realpath`, `isdir`, `fsencode`, `PyDict_*`) | front end: `wasi_python.h` fills a plain-C `wasmext_wasi_config` (args, env, preopens `{name, host path, readonly}`, hooks, `user`); the core takes that |
| Python objects in the state | `stream[3]`, `stdin_pos`, `exit_type`, `signal_type`, `ended_type`, `time_module`, `os_module`, `text_base`, `clock_fn`, `random_fn`, `cfg_*`; `wasmext_wasi_traverse`/`_clear` | the state holds references | out of the core state: the core has `void *user`, and the Python front end keeps these in the structure `user` points to (and does the GC traversal) |
| Standard streams | `wasi_is_text`, `wasi_write_text_stream`, `wasi_write_bytes`, `wasi_write_std`, `wasi_read_bytes`, `wasi_read_std` | text or binary stream, `sys.stdout` as it is now, bytes as stdin | hooks `stdin_read`, `stdout_write`; without hooks the core reads and writes descriptors 0, 1, 2 itself (what the executable needs) |
| Clock, random | `wasi_clock_ns`, `wasi_random_get` | a function the caller gave | optional hooks `clock`, `random`; the system's own is already plain C |
| Sleep | `wasi_sleep_ns` | releases the interpreter and checks `PyErr_CheckSignals` between slices | hook `sleep`; the default (slices of 100 ms, `nanosleep`/`Sleep`) stays in the core |
| End of the program | `wasi_proc_exit`, `wasi_proc_raise`, `wasmext_wasi_finish`, `wasmext_wasi_check` | builds `WasiExit`, `WasiSignal` and raises them in the call | the core records the end (`finished`, `end_value`) and reports a trap; the front end makes the exception from that record when the call returns (`wasmext_wasi_check` is already there) |
| Errors of Python | `wasi_python_error` and every `return wasi_python_error(trapped)` | an `OSError` becomes a WASI errno, anything else a trap | disappears from the core; becomes the protocol of hooks (below) |
| Files of Windows | the block `#if WASMEXT_WASI_PYTHON_FS` of `wasi_common.h`, lines 1349–1930 (about 580 lines; the whole `#if … #else … #endif` with the POSIX half is 1005 lines) | `os.stat`, `os.open`, `os.listdir`, `normcase`, times through `os.utime` | stage 3: replaced by a native backend; until then a backend of `wasi_python.h` |
| Two small `#if` | `wasi_fill_preopen`, `wasi_sync_entry` | the same switch | go with the backend |

Everything else in the file (memory access, rights, descriptors, the walk of a path, `openat` and its kin, the translation of errno)
has no Python in it; the POSIX half is plain C already, and its only link to the interpreter is `wasmext_wasi *w` and the argument
`trapped`.

### The hooks

One structure given at creation, in the configuration; every hook is optional, and a missing one means the default of the core.
`user` is the host's own state; the core never frees it, and the front end owns its lifetime (it must outlive the instance).

| Hook | Signature | Default of the core |
| --- | --- | --- |
| `stdin_read` | `int (*)(void *user, uint8_t *buf, size_t cap, size_t *got)` | `read(0, …)` |
| `stdout_write` | `int (*)(void *user, int fd, const uint8_t *buf, size_t n)` (`fd` 1 or 2) | `write(fd, …)` |
| `clock` | `int (*)(void *user, uint32_t id, uint64_t *ns)` | the system's clock |
| `random` | `int (*)(void *user, uint8_t *buf, size_t n)` | the system's source |
| `sleep` | `int (*)(void *user, uint64_t ns)` | slices of 100 ms |

Return of every hook: `0` is success; a positive number is an errno of WASI (`WASI_E_*`) that the core hands to the program
unchanged (a broken pipe is `WASI_E_PIPE`, an unreadable stream is `WASI_E_IO`); `WASI_HOOK_TRAP` (a value outside the errnos) is a
trap of the call. The host keeps what it needs for the report (the Python layer keeps the exception it caught, see the protocol).
The text-or-binary logic of `stdout_write` is the Python layer's, not the core's.

Whether hooks are `static inline` functions chosen by a define or pointers in this structure is **not decided here** (stage 2 measures
it); the table is written for pointers because that is the case the other front ends (shared library, executable) need.

### The interface of a file backend

`wasi_be_*` already is that interface: there are two implementations of the same 12 functions (the Python one at 1349–1930, the POSIX
one at 1931–2353) and the code after them calls only the names. What changes is how they are shaped:

- `stat_fd`, `stat_path`, `open`, `mkdir`, `remove`, `times_fd`, `times_path`, `rename`, `link`, `symlink`, `readlink`, `list`
  (that is the whole set; `sync` and `seek` use the descriptor directly).
- They no longer take guest pointers (`uint32_t path, len`) or `trapped`: the core copies the name out of the memory of the module,
  checks it, and gives `const char *` and its length; the result is a WASI errno. A backend does not know the module has a memory.
- A directory is an `wasi_entry`; what it keeps in it (a POSIX descriptor, a Windows handle, a root and a relative path) is the
  backend's business, so `osfd` becomes `uintptr_t handle` plus the backend's own fields. The POSIX and the Win32 backend are shaped
  by that: Win32 has no `openat`, so the portable one holds a handle of the directory and the path below it and checks that the real
  path stays inside the preopen; the `nt` one opens relative to the handle.
- Selection is by define at build time (`WASMEXT_WASI_FILES=posix|win32|nt|python`), not by compiler.

### The protocol of errors of host functions

The same for the hooks of WASI and for the functions the host gives through `imports`: **the status is the return value, and the
exception, if there is one, is the host's own object.**

- A host function in a language with exceptions catches everything inside its callback, keeps the exception object, and returns
  `WASI_HOOK_TRAP` (for `imports`: the same, a trap code of the call).
- The core raises a trap in the module with `trapped` set; the call ends, and the export reports `trapped` and a code.
- The front end that made the call looks at what it kept and raises that, so Python raises the very object its function raised.
  Nothing crosses the C frames of the module as an exception; this is the pattern of wasmtime, wasm3 and wasmtime-py.

Known from reading the headers of wasm3 and wasmtime only; checked against the real behaviour of neither.

### The three outcomes of a call

A call to an export ends in one of these, and the C interface has to carry all three (today the third is `Trap('Uncaught exception')`):

1. **A value** (or none).
2. **A trap**: the code of `wasm_rt_trap_t`, and for a host trap the object the front end kept.
3. **An uncaught exception of WebAssembly**: the tag and the values (`wasm_rt_exception_tag`, `_size`, `_exception`; up to 256
   bytes). The front end of Python makes `UncaughtException(Trap)` with `.tag` and `.values`; the C interface gives the tag index,
   the number of bytes and a pointer valid until the next call. Tags of the module are read from the tag section when the glue is made
   (stage 4); importing a tag from the host is not supported.

### Names of the files

| File | Layer | Python.h |
| --- | --- | --- |
| `wasmext_glue.h` | universal glue: instance of the runtime, link record, the three outcomes | no |
| `<name>_glue.h` | glue of the module: typed functions (`link_call0` …), tables | no |
| `<name>_py.c` | the extension: types, methods, the stubs of the capsule | yes |
| `<name>_shared.c` and `<name>_api.h` (stage 6) | the stub of the shared library and its C header | no |
| `<name>_exe.c` (stage 7) | `main()` | no |
| `wasi_core.h` | WASI without the host | no |
| `wasi_preview1.h`, `wasi_unstable.h` | the two interfaces (stay as they are) | no |
| `wasi_python.h` | hooks and configuration of Python | yes |
| `wasi_files_posix.h`, `wasi_files_win32.h`, `wasi_files_nt.h` | file backends | no |
| `wasi_files_python.h` | the Python backend; leaves when 3a is green on Windows, unless the Linux job that tests the Python path is worth keeping | yes |

### What the shared library and the executable need from the core

- **Entry points**: create an instance with a configuration (arguments, environment, preopens, hooks); call an export (by index, with
  typed arguments and results, or a `uint64_t` array); read and write the linear memory; free; the link record, for linking instances.
- **Commands and reactors**: the executable calls `_start`, ends on `proc_exit` with its code, and takes `args` from `argv`, `env`
  from the environment and the preopens from `--dir` options; a library calls `_initialize` (if the module has it) and then the
  exports.
- **Nothing of Python**: no hook of the core may need the interpreter to finish; this is the check (a) of the plan.

### Not decided at this stage

Hooks as pointers or `static inline` (stage 2 measures); one release for stages 6 and 7 or two; whether `wasi_files_python.h` stays;
the exact errno for a host function that cannot report one; the interruption of a sleep in a library that has no signals.

### Stage 2, as built

`wasi_common.h` is now `wasi_core.h` (1959 lines, no Python) and `wasi_python.h` (1193 lines). Checked: the 303 tests and 4 expected
failures as before (the tests of the files run the POSIX backend and the Python one); the core with `wasi_preview1.h` and
`wasi_unstable.h` compiles with gcc and clang (`-std=c11 -Wall -Wextra`) with **no Python on the include path** (check (a), Linux).
CI: the official WASI tests on the three systems pass on this stage (`1c5a8b8`). Check (a) is its own workflow, `core-without-python.yml`: the
core with the two snapshots compiled by gcc and clang on Linux and by clang on macOS with only the runtime of wasm2c on the include path, and
a search that the core files do not name the Python C API. Windows (MSVC) joins at stage 3: until the file backend there is native, the core
there takes the one of `wasi_python.h`.

What differs from the table of stage 1:

- **One more hook, `end`** (`proc_exit`, `proc_raise`), called before the program is marked as over. The plan said the core would only
  record the end and the front end would make the exception later; the hook keeps the glue as it was (the exception is set at the
  moment of the call, as before) and costs one pointer. Python's `end` raises `WasiExit` / `WasiSignal`.
- **`wasmext_wasi_create(config, &err, &bad)`** is the plain-C constructor; it copies the configuration (the host may free it at once).
  `wasmext_wasi_new` (the dict) stays for the glue and lives in `wasi_python.h`, with `_free`, `_clear`, `_traverse`, `_check`; the
  core's own freeing is `wasmext_wasi_destroy`.
- **The Python objects are in `wasmext_wasi_py`**, which the core sees only as `user`. A failed hook leaves its exception in the state
  of the thread and returns `WASI_HOOK_TRAP`; an `OSError` becomes an errno of WASI (`wasi_python_status`).
- **The file backend kept its form** (guest pointers and `trapped` in the `wasi_be_*` functions). Cleaning that up is left to stage 3,
  where a second backend shows what the interface needs; for now the core declares the twelve functions and either its own POSIX half
  or the Python half of `wasi_python.h` defines them (`WASMEXT_WASI_PYTHON_FS`, which is the default on Windows).
- **Memory** is `malloc`/`free` (macros `WASI_MALLOC`…), not `PyMem_*`, so a host without Python links nothing else.
- **Without hooks** the core reads descriptor 0 and writes 1 and 2 itself, sleeps in slices of 100 ms, and uses the system's clock and
  random source; that is what the executable of stage 7 will run on.
- **The glue** includes `wasi_python.h` after the header of the snapshot; `wasi_core.h` and `wasi_python.h` are copied beside the glue
  (`WASI_SHARED` in `_natify.py`).
- Still open (stage 2 was to measure it): hooks as pointers or `static inline`. They are pointers now; nothing was measured.

### Stage 3a, as built

`wasi_files_win32.h` (about 880 lines, Win32 only, no Python, no POSIX layer) is the file backend of the core on Windows; it is chosen by
`_WIN32` and replaced by the backend of Python with `-DWASMEXT_WASI_PYTHON_FS=1`. It has the twelve `wasi_be_*` functions of the interface
and keeps the model of the Python backend (a directory is a path; a file is a descriptor of the C library made with `_open_osfhandle`, with its
path kept), so `fd_read`, `fd_write`, seek, truncate and sync of the core are the same code on every system. The calls are the documented
wide-character ones: `CreateFileW` (with the same sharing as the C library, read and write), `GetFileInformationByHandle` and `...Ex`
(identity, size, times, link count, reparse tag), `FindFirstFileExW`, `MoveFileExW`, `CreateHardLinkW`, `CreateSymbolicLinkW`,
`DeviceIoControl(FSCTL_GET_REPARSE_POINT)` for `readlink`, `SetFileTime`. Paths go as UTF-16 with the `\\?\` prefix. A name is resolved by
hand below the directory; a link that leads out is found by comparing `GetFinalPathNameByHandleW` of what is used and of the directory (so the
check and the use are two steps: what `openat` does not have, and what the `nt` variant of 3b is for). A link that leads nowhere is refused
when a name is to be made through it (where it would lead is not known).

What was checked, and what was not:

- The same C test (`/tmp` scratch, not in the repository yet: about 100 calls of `path_open`, `fd_*`, `path_*` on a directory, the answers
  printed) was run on POSIX and on Windows under wine (the C compiled by `zig cc -target x86_64-windows-gnu`, run by wine 9). The answers are
  the same for creating, reading, writing, truncating, appending, `stat` with and without a trailing slash, `readdir`, `rename` (a file
  over a file, a directory over an empty directory, the refusals), `unlink`, `rmdir`, hard links, `..` out of the directory, an absolute
  name. They differ in the link count and size of a directory (Windows says 1 and 0), and in `a/../d1` where `a` does not exist (the name is
  resolved without looking at the disk, as in the Python backend).
- **Symbolic links and `atim` of `path_filestat_set_times`** could not be checked under wine (it does not do the reparse points of Windows and ignores the access time), so the CI was the first test:
  **it is green** (the 72 official tests on `windows-latest` with this backend, and as a second job with the Python one). On x64 only: ARM64 and x86 are not run for the suite.
- The official tests expected `symlink_filestat` to fail on Windows with Python before 3.13; with this backend it should pass, so the
  expectation file now belongs to the job of the Python backend only (`expectations-windows-python-fs.toml`), and the job of the native
  backend has none. Whatever fails there is read from the first run.
- Check (a) now includes MSVC on Windows (`core-without-python.yml`).

### Stage 4 (the glue as files), first half: as built

`generate()` makes three layers where it made one file. **Written and tested** (303 tests, 4 expected failures at the time, plus a test that the glue of a module
compiles with no path to `Python.h`); **run in CI since, green on the three systems**.

- `wasmext_glue.h` (static, no Python, copied beside every module): the trap codes that are not the runtime's (`WASMEXT_TRAP_HOST`,
  `_NO_MEMORY`, `_ENDED`), the fingerprint `WASMEXT_RUNTIME`, how a call of WebAssembly code is guarded (`WASMEXT_ENTER` / `LEAVE`, the
  jump buffer, the signals of a trap by guard pages).
- `<name>_glue.h` (generated, no Python): what each import module holds (`fn[]`, `user[]`: the function to call and its first argument,
  the values of imported globals, the pointers of imported memories), the instance `<name>_instance`, the functions the module imports in
  the form the runtime wants (over `fn`/`user`), `<name>_instantiate`, `<name>_free`, and for each export a typed function
  `<name>_call<i>(void *instance, parameters..., int *trapped)`: `*trapped` is the code of the trap, or 0.
- `<name>_py.c` (generated, was `<name>_glue.c`): the Python layer: `Instance`, the conversion of arguments and results, `py_import<k>`
  (a callable of the caller as a host function whose `user` is the callable), the capsule `wasmext.export.v1` (its record and fingerprint are
  as they were), the memories and globals as attributes. `py_link<i>` is what a capsule gives another Python extension: the typed function,
  with a trap turned into an exception of **this** extension before it is answered (so that `a.Trap` is still the exception of a trap in `a`).

Notes: a call across two instances is now a call of a function pointer with `user`, the same for a function of another instance, one of WASI
and a Python callable (the old `lf`/`li` and `fn` fork is gone). The protocol of errors is what the glue does: a host function answers
nonzero through `trapped`, the frames of the module are unwound with `WASMEXT_TRAP_HOST`, and the Python layer finds its exception where Python
keeps it. The check (a) in CI (`core-without-python.yml`) does not cover the new headers; `test_the_glue_of_a_module_compiles_with_no_python`
does it on systems with a `cc`, and the tests of the shared library and of the executable compile the glue with no path to Python on all three systems (MSVC included). **Second half of stage 4: built** (the tags, below). Still to do for the C API: stage 6.

### Stage 4, second half: the uncaught exception of WebAssembly, as built

`_wasm.py` reads the tag section (`Module.tags`, `all_tags`; the check of the indices of exported tags is real now). The glue of a module that has tags
(`<name>_glue.h`, no Python) gets `<name>_tag_of(tag)` (the index of the tag of the exception the runtime keeps, or -1 for the tag of another module) and
`<name>_tag_values(tag, payload, size, out)`, which decodes the bytes the runtime keeps by the types of the tag into `wasmext_value` (a type number and a
union; `wasmext_glue.h`). The Python layer makes `UncaughtException(Trap)` with `.tag` and `.values` from them when a call ends with
`WASM_RT_TRAP_UNCAUGHT_EXCEPTION`, before any other code of WebAssembly runs (the runtime keeps one exception per thread); the stub names it.

How the glue finds the tag: wasm2c makes the tags of a module `static` (in one file) or gives them names that depend on the export, so natify adds to the
C of wasm2c, in the first (or the only) file, a table `wasmext_tags_<prefix>[]` of their addresses in the order of the tags (`_export_tags` in
`_natify.py`; it reads the declarations `const wasm_tag_placeholder_t NAME;` that wasm2c writes, in that order). The payload is the value itself for a tag with
one value and a struct of them for more (wasm2c's own `struct wasm_multi_<codes>` is not in the header, so the glue declares the same members in the
same order). Limits: the runtime keeps at most 256 bytes of an exception; a tag with a reference type in its values is told by its index with no values.

### Stage 5, the C runner (check (b)), as built

`wasmext._exe` makes a native program from a WASI command: the C of wasm2c (by `_prepare` of natify, so the same repairs), `<name>_glue.h`, the core of WASI
and a generated `main()` (`<name>_main.c`), compiled and linked by the compiler of `setuptools` (MSVC on Windows, `cc` elsewhere). No Python is in the program. The program takes
`--env NAME=VALUE`, `--dir HOST::GUEST` (both repeated), the path of the module and its arguments, and ends with the code of `proc_exit` or 134 on a trap. Only the imports of
WASI are served (`<name>_wasi_bind` in the glue); a module with any other import, or with no `_start`, is refused when it is made. On Windows the standard streams are put in
binary mode and the host path of a directory is made whole (`_fullpath`).

**Checked**: on Linux the 72 official tests of the suite pass with these programs (all built in 80 s, run in 1.5 s, against about 7 s through Python); three tests in `tests/test_exe.py`
(exit code and bytes, a trap, the refusals). **Then run on macOS and Windows** by the CI jobs `(native executables)` of `wasi-testsuite.yml`: Windows passed at once; macOS failed three tests (`path_link`, `stdio`, `path_open_preopen`, `NOTDIR` for `ISDIR`), which valgrind on Linux traced to
`wasi_path_open` using the entry of the directory after `wasi_new_fd` had grown (reallocated) the table of descriptors; fixed, and all 72 programs are clean under valgrind. Green on the three systems.
This is the tool of the test suite, not yet a command (`natify --exe` is stage 7).

### Stage 6a, the shared library with a C API: built and closed

`wasmext._shared` makes, from the same typed glue, a public header `<name>_api.h` (plain C types, no wasm2c types) and `<name>_shared.c` that exports it; `_exe.build_shared` compiles and
links them into a shared library (the sources of wasm2c, the glue and the core of WASI; no Python, and no `main`). The life of an instance: `<name>_new(&config, &error)` (WASI is made and
bound there), `<name>_set_import<k>(m, f, user)` for each import that is not WASI's (a host function `result f(void *user, params..., int *trapped)`, the protocol of errors above),
`<name>_instantiate(m)` (0 or the code of a trap), each export as `int <name>_<export>(m, params..., results...)` (0 or the code of a trap; `<name>_trap_message(code)` is its text), `<name>_free(m)`.
A module that imports a global or a memory, or has several results in an import, is served now (see "Then built" in the audit below); `v128` in an import was refused with a clear message (served now, as 16 bytes behind a pointer; see the row `v128` in a signature).
Checked by `tests/test_shared.py` with a host written in C, on Linux, macOS and Windows (MSVC) in CI. What was open when 6a was written is closed: Windows runs it, the configuration of WASI has the
hooks of the clock, random bytes, sleep and the end of the program, a reactor is initialized by `_instantiate`, the globals have accessors, the link record for linking instances is in the API.

**The products, decided** (for stage 7): `--extension` (the default when no product is named), `--shared` and `--exe` are *one product for each run*, not combinable: a library must not hold a
`main`, and an executable has its own, so they are separate builds of the same C (the C of wasm2c and the glue are shared by the work directory and not made twice). Naming `--shared` or `--exe`
builds only that; the extension is built only when it is the default or asked for. `--exe` needs a `_start` (a command). A reactor (WASI module with `_initialize` and no `_start`) is a
`--shared` product: done, in every front end: one function of the glue (`<name>_glue_initialize`) runs `_initialize` of a reactor once after the instantiation, the extension, the library and the ctypes wrapper call it, and a later explicit call of `_initialize` does nothing; a trap in it is the error of making the instance. A module with a `_start` is a command and is not initialized.

### Stage 7, how the products are asked for (built, with the wheel tag)

A package may ship a shared library (a dll) or an executable instead of, or beside, a Python extension, so the product is a setting of **both** doors, not only of the command line:

- `natify(..., product="extension" | "shared" | "exe")` (default `"extension"`) and, with the same name, a key `product` in `[[tool.wasmext.ext-modules]]` of `pyproject.toml` (the hook reads the table and calls `natify()`); `natify()` keeps returning `Extension` objects.
- One product for each entry: several products of one `.wasm` are several entries (an array of tables), each with its own output name. The command line says the same with `--shared` and `--exe` (`--extension` is the default when none is named), one product for each run, since a library holds no `main`.
- A product that is not an extension is an `Extension` with a mark that `wasmext._setuptools` (the `build_ext` it already puts in) knows: it compiles `<name>_shared.c` or `<name>_main.c` in place of the Python layer, links a library (`lib<name>.so`, `lib<name>.dylib`, `<name>.dll` with its import library) or an executable (`<name>`, `<name>.exe`) and puts the file where an extension would go, so `package-data`, `inplace` and wheels work as they do for an extension.
- **Built:** `natify(product=)`, the `product` key of the table (type-checked), `--extension`/`--shared`/`--exe` (exclusive; as for an extension, the C is only written unless `-i` or `-b`), the `build_ext` of `wasmext._setuptools` (`get_ext_filename`, `build_extension`, the wrapper copied to the source folder with `-i`), `tests/test_products.py`. The C of every target is made when `natify()` is called, whatever product is asked for; the CLI ignores the table of the project it runs in (`WASMEXT_NO_PYPROJECT`).
- **Done:** the tag of a wheel that has no Python extension (`py3-none-<platform>`). **Decided:** a package finds its own binary by its own code (wasmext builds, the project distributes; there may be several programs, and a project may not want a launcher). The header `<name>_api.h` stays in `<name>_wasmext/` and a `package-data` entry for it works (the C of a product is made when the project is read).

### Stage 6b, the wrapper for ctypes, as built

`build_shared` also writes `<name>_ctypes.py` and `<name>_ctypes.pyi` beside the library (`wasmext._ctypes_gen`; the stub is the one of the extension). The module is Python only, needs nothing of wasmext, finds the library beside itself
(or at `$WASMEXT_<NAME>_LIBRARY`) and has `Instance`, `Trap`, `LinkError`, `UncaughtException`, `WasiTerminated`, `WasiExit`, `WasiSignal` as the extension has them: methods with their signature as the docstring, the same type errors and wrapping of
integers, `imports` as callables (the exception of an import comes out of the call as the very object, by the protocol of errors: the callback keeps it and answers `trapped`), the memory as a `memoryview` that keeps the instance alive, globals as attributes,
`wasi={...}` with the same keys and the same errors, a call of WASI replaced through `imports`, `__exports__` and `__getitem__`, and the linking of instances.

**Linking is C in the core, not Python.** The record of an export (`wasmext_export`, in `wasmext_glue.h`; the extension wraps it in a capsule `wasmext.export.v1`) and the checks that link an import to it live in `<name>_glue.h`
(`<name>_link_func<k>`, `_link_global<j>`, `_set_global<j>` for a number, `_link_memory<j>`; the messages are the ones the extension always gave). The extension, the C API (`<name>_link_import<k>`, `_link_global_import<j>`, `_set_global_import<j>`,
`_link_memory_import<j>`, `<name>_export_find`) and the wrapper all use them, so the front ends link **with each other**: a wrapper takes the memory, a global or a function of an extension, and the other way (tests: `tests/test_linking.py`, the pairs
extension/extension, ctypes/ctypes, extension/ctypes, ctypes/extension). A function of a library is linked as a C function, with no Python in between (flag 8 of the record: it needs no GIL), and a trap of the callee goes through as it is
(`WASMEXT_TRAP_LINKED` + its code, see `wasmext_glue.h`); a function of an extension needs Python (its `py_link` raises exceptions), so a wrapper calls it through Python. A host function that fails in an instance that is called through a link: the
instance that was called keeps the exception (`_pending`) and the caller raises that very object. The capsule of a wrapper keeps the instance alive and owns its record, as the capsule of an extension does.
**Two libraries in one process** each have a runtime of wasm2c of their own: the library shows its API and no other symbol, which is fixed by the **linker** and not by a flag of the compiler (a version script, or `-exported_symbols_list` on macOS; MSVC exports what is
`dllexport`; the list is written beside the C as `<name>.map` / `<name>.exports`, for a build system of one's own). Without it the two share the buffer of `longjmp` and a trap through a link aborts.
**Flags of the user**: `BuildFlags` (`extra_compile_args`, `extra_link_args`, `define_macros`, `undef_macros`, `include_dirs`, `libraries`, `library_dirs`: the names of `setuptools.Extension`) go to `build_shared` and `build` after the flags of wasmext, so they win; the environment
is read as setuptools reads it (`CC`, `CFLAGS`, `CPPFLAGS`, `LDFLAGS`; `_CL_` for MSVC).
What the C API got for it: `set_import` for the calls of WASI too, imports with several results (through pointers), imports of globals and memories, `dirs_readonly`, `args` non-NULL with `nargs` 0 for "no arguments", and the export records.
**The proof**: the tests of the interface run on both front ends and pass: `test_extension.py`, `test_wasi.py`, `test_wasi_fs.py` (the files of the system), `test_linking.py`, and the examples of pywasm3, wasm2mpy and wasmhost.
**Differences that stay**: a trap that goes through a link out of a library is the `Trap` of the instance that called, not that of the callee; a function of a wrapper that is given to an extension is called by it directly (no Python), one of an extension that is given to a wrapper
goes through Python; the interruption of a sleep by Ctrl-C (the core sleeps in C); PyPy and GraalPy (not tried); where the library is shipped (stage 7).

### Audit of stages 1 to 6a against the plan (after 6a; probes run by hand, not yet tests)

**Bugs found by running the shared library** (the four are fixed, each with a test in `tests/test_shared.py` or `tests/test_exe.py`; the fixes: `_new`, `_instantiate` and every export set the runtime up for the calling thread by `api_enter()`, with `<name>_thread_free()` to give it back; the end of a WASI program answers `TRAP_ENDED`; an export left out is said in the header (`not here:`) and on stderr; an executable of a module with no WASI import is refused in words):
- The library never calls `wasm_rt_init()` (the extension does it in `PyInit_`, the executable in `main`): an out-of-bounds access in a module **crashes the host with SIGSEGV** instead of
  answering a trap (the only trap the test uses is `unreachable`); a build without `NDEBUG` (a Windows build by `zig cc`) stops at `assert(wasm_rt_is_initialized())`. `_new` must call it (it is idempotent), and a
  host thread other than the one that created the instance needs `wasm_rt_init_thread()`.
- The call in which a WASI program ends (`proc_exit`) answers `TRAP_HOST` ("a host function failed"); only later calls answer `TRAP_ENDED`, which is what the header documents for the end.
- An executable of a command that imports nothing from WASI stops in a C `#error` of the generated `main` instead of running or being refused in words.
- An export with `funcref`/`externref` in its signature is left out of the header without a word (a v128 one was said; it is in the header now), and a table export is accepted where the extension refuses it.

**Then built** (tests in `tests/test_shared.py`): the configuration of the library has the hooks `clock`, `random` and `sleep` as well as stdin and stdout; `_instantiate` runs `_initialize` of a reactor (a module that has it and no `_start`) after the instantiation, so that
the first export already sees its effects (the extension does the same now, through the same function of the glue; see "Stage 7"); every exported global
of type i32, i64, f32 or f64 has `<name>_global_<g>(m)` and, when mutable, `<name>_set_global_<g>(m, value)`. The tests run on Windows too: the host is compiled by the compiler of setuptools (MSVC) against the import library that `build_shared` copies beside the dll
(`libm.lib`), so the CI of the three systems ran it on MSVC: **green** (02a841e; the first run found that a path of an object past 260 characters broke `cl`, now the objects are named by the stem); checked by hand before: the library cross-built by `zig cc` (MinGW) and run under wine answers an out-of-bounds trap, the end of a WASI program and a reactor.
Because these tests compile `<name>_glue.h`, `<name>_api.h` and the core with no path to Python on each system, they are check (a) for those headers too (the dedicated workflow `core-without-python.yml` compiles them strictly too now: the glue, the C API and the `main()` of a few modules, made by `.github/scripts/glue_without_python.py`, with gcc, clang, macOS clang, MSVC and MinGW by `zig cc`; the strict build found `#pragma comment(lib)` of MSVC unknown to MinGW, and static functions of the glue header that clang warned of as unused, now `static inline`).

**Left from the list below** (still open): the file-backend and naming deviations, 3b (`nt`) and the measure of hooks, ARM64 and x86 for the suite. Closed since: the link record is in the API, 6b and stage 7 are built, the 'as built' texts of 3a, 4 and 5 are refreshed.

**In the plan and not there (as found; the hooks, `_initialize` and the globals are now there, see above)**: a reactor's `_initialize` is not called by `_instantiate`; the configuration has the hooks of stdin and stdout only (the core also has `clock`, `random`, `sleep`; the `wasi=` of Python has the user
functions for the clock and the random bytes, so 6b needs them); exported globals have no accessor (the extension has them as attributes); the link record for linking instances is not in the API; Windows (MSVC)
had never built the library at that time (cross-built by `zig cc` as a MinGW dll, it exported and linked, and ran under wine up to the missing `wasm_rt_init`; MSVC has built and run it since, see above); the proof is two tests and one host.

**Plan deviations not written down before**: the file backend kept its form (guest pointers and `trapped` in the `wasi_be_*` functions; the plan wanted `const char *`, no `trapped`, a handle); the selection by
`WASMEXT_WASI_FILES=posix|win32|nt|python` and the files `wasi_files_posix.h`, `wasi_files_nt.h`, `wasi_files_python.h` do not exist (it is `_WIN32` and `WASMEXT_WASI_PYTHON_FS`); the file of `main` is
`<name>_main.c`, not `<name>_exe.c`, and `wasmext-run` is not a command; stage 3b (`nt`) is not started; hooks as pointers or `static inline` was never measured. Check (a) in CI
(`core-without-python.yml`) does not compile `wasmext_glue.h`, `<name>_glue.h` or `<name>_api.h` (a test of pytest does it on Linux and macOS, skipped on Windows; MinGW or `zig cc` is not in CI). Item 9 says the
official tests were checked on Windows x64, ARM64 and x86: the suite, the native backend and the executable run in CI on x64 only (ARM64 and x86 build the example wheels).
The text of "Stage 3a", "Stage 4 first half" and "Stage 5, as built" above still says the CI had not run; it has, and is green on Linux, macOS and Windows (the suite on the extension, on the Python files, on the executables).

**Checked and sound**: no Python in the core files (grep, and CI with gcc, clang, macOS clang and MSVC); the 72 official tests pass on the extension, with files through Python and as native executables, on the three systems, and
all 72 executables run clean under valgrind (this found the use of a freed table in `path_open`, now fixed); an out-of-bounds trap in an executable and in the extension (also from another thread) is a trap; the library
passes the probes for WASI with and without hooks, a preopened directory (a file is written), i64/f32/f64, several results, two instances, a growing memory, a free of NULL, and a clean valgrind.
Built since this audit: 6b (ctypes), stage 7 (`product`, `--shared`/`--exe`), the README section on products.

### Audit, second round: what was fixed, and what is still not covered

**Fixed, each with a test**: a half-made instance is freed when `instantiate` traps (a start function that traps, a data segment out of range), but **not after `NO_MEMORY`**: the memory that
could not be had has a size and no data, and the runtime frees it with `munmap(NULL, 8 GiB)`, which unmapped the interpreter itself (found by `test_a_limit_on_address_space`; a memory of the module made
before the failed one leaks then, which is rare and harmless next to a dead process); a table that cannot be allocated is a `MemoryError` (the glue tries the same `calloc` first); names with a NUL, with `*/` or a newline cannot
break the C or its comments; imports are bound by the name of the import module, as wasm2c orders them; an exception tag with a payload of more than 256 bytes (what the runtime keeps) is reported when the extension is made; `wasi_python.h` used
`Py_SETREF` and the `GET_SIZE` macros, which an abi3 build does not have (an `undefined symbol` at import; now only limited-API calls); the executable has `--help`, `--version`, `--argv0`, `--`, `HOST::GUEST:ro`, a validated `--env`,
the errno in its errors, the number of the signal, UTF-8 arguments on Windows (checked under wine with `zig cc`) and a refusal of a `_start` that is not `() -> ()` in words; the table of `pyproject.toml` checks the type of each value and
names the key; `wasmext inspect` takes the list of what is left out from the generator, so it cannot call a method what the generator does not expose; a module with GC types or a custom page size is refused with the name of the proposal; `-q` silences the
warnings of the compiler for the C of wasm2c too; the release workflow does not publish a commit on which `pre-commit.yml` (pytest on three systems) has no successful run.

**Not covered, and said so**:
- A call into a function of another instance that raised in its host function came out of the extension, once in CI (`Coverage`, Linux, Python 3.11, the `ctypes`→extension case of `test_an_exception_of_a_function_of_another_instance_comes_out_of_the_call`), as a `SystemError`: *returned NULL without setting an exception*. It did not come again in 11 runs alone, with coverage, and with the collector at a threshold of 1, and 7 earlier runs of that job on the branch passed. `raise_trap` set the exception and then called Python (`PyObject_SetAttrString`) with it set, which can run a finalizer or the collector and lose it; it now clears the attribute first and sets the exception last, and a trap always leaves an error (a `Trap` if nothing else). The cause is not proved: no test fails without the change.
- The fixtures `build_extension` skips on Windows (it uses a `cc` and the build line of gcc/clang), so **the tests of the Python extension front end do not run on Windows**; there run the ctypes front end, the shared library, the executable, the official WASI suite and the example wheels
  (all of them build the extension with MSVC). Turning `build_extension` into a build by the compiler of setuptools is the way to close this, and needs CI rounds on Windows.
- abi3 is tested by the suite with Python 3.11 and 3.15 (the wheels are tagged `cp311-abi3`); 3.12 to 3.14 run the wheel of coremark in the job `abi3-wheel-on-newer-pythons` (passed locally and in CI); a free-threaded build has none.
- The patches of the copy of the C that wasm2c writes are four: `_memory_error_not_abort` (the allocation of a memory traps, it does not `abort()`), `_export_tags` (the table of tags), `_tail_call_locals` (fixed in WABT master by `6c7af19`, not in a release),
  `_portable_on_arm64` (`_addcarry_u64`, WABT #2885). Nothing in the runtime or the sources of wabt-package is changed; when WABT has a release with the fixes the patches go.
- **Fixed:** an exported `memoryview` of a memory that the runtime moves when it grows (no guard pages, memory64) used to be able to outlive the buffer. Now `memory.grow` answers -1 while such a view is alive (the maximum is made the present size; `Py_bf_releasebuffer` puts it back), in the extension and in the ctypes wrapper (`<name>_memory_*_pin` of the C API, a finalizer of the view); `test_a_memory_that_can_move_does_not_grow_while_a_memoryview_of_it_is_alive`.

## Decisions

- **The generated C is not a format of distribution.** A mode in which a project ships the C and a user builds it with a C compiler alone (no wasmext) is cut: it would need the folder of a module to hold everything the C includes (the runtime of wasm2c, the headers of simde, 8 MB for a module with SIMD), a promise that the C of one version of wasmext stays valid for a compiler of another, and tests nobody asked for. A build needs wasmext, and through it the wabt-package. The sdist may carry the C (it is made when the project is read, so that `package-data` can name a file of it on the first build), and a project that follows the advice of Cython leaves it out with `global-exclude *_wasmext/*`.
- **Distribution is the project's.** wasmext builds a library or a program and puts the file where an extension would go; it does not decide what a package does with it. No helper that finds a program or a library at run time (a library has its generated wrapper, which looks beside itself; a program is found by the package's own code, a `[project.scripts]` entry of its own, or not at all), and the header `<name>_api.h` is not put in the wheel by default (only a host outside Python builds against it; a `package-data` entry puts it there). The names of the files are documented (`lib<name>.so`/`.dylib`/`<name>.dll`, `<name>`/`<name>.exe`). The header `<name>_api.h` is in `<name>_wasmext/`; a project that wants it in the wheel names it in `package-data`.
- **The public interface (alpha).** Three tiers, written in the README ("Public interface"): *stable* (the module that wasmext makes, `natify()` and the options and `pyproject.toml` keys, the user's environment variables, the products' header, wrapper and command line, `__version__`, `GenError`, `WasmError`), *provisional* (`generate`, `parse`, `Glue` and the parsed types, `find_toolchain`, `Toolchain`, `wasmimport`), *private* (the `_*` modules, the setuptools hook, the C and its headers, the `WASMEXT_*` macros, and the link between instances). The link record (`wasmext.export.v1`, `wasmext_export`, `<name>_export`) is **private and opaque**: it was said to be private "until a second user exists", and the header of a library does carry its struct, so the rule is that a reader passes it and does not read its fields; it is not a contract for other hosts. Open: whether to move the struct out of the public header; a test that pins its layout; the fingerprint `WASMEXT_RUNTIME` does not yet cover `wasm_rt_funcref_t`, `wasm_rt_externref_table_t` and `wasm_rt_shared_memory_t`, so adding tables, references or threads to the link would change it.

- **Platforms.** `wasmext` is a pure Python wheel (`py3-none-any`) that depends on the wabt-package, so it installs wherever the
  wabt-package has a wheel (or builds from its sdist with a C++20 compiler): the platforms of `wasmext` are the platforms of the
  wabt-package, and nothing else limits them. Both packages cover the desktop platforms of `cibuildwheel` and nothing outside them
  (no Android, Pyodide or iOS wheels of the tools: `wasm2c` runs on the machine that builds, and an extension for Android or
  Pyodide is built with the wheel of the host, checked on `examples/coremark`). For the wabt-package the wanted set is Linux
  (manylinux and musllinux: x86_64, aarch64 as the core; i686, armv7l, ppc64le, s390x, riscv64 as well), Windows (x64, ARM64; x86 as well)
  and macOS (arm64, x86_64; universal2 as well). Every wheel is linked statically against the C++ runtime (a test checks it on every platform).
  `zig cc` is not a requirement of anyone: it only builds `_core.wasm` of the example (the `wasm` dependency group of this repository, not installed by default); the user of
  wasmext brings a `.wasm` made by whatever they like. The platforms of the packages that are built *with* wasmext (like `coremark`)
  can be more than these, Pyodide and Android among them.

- The glue is plain CPython C API, not nanobind, pybind11 or Cython: it is generated, targets abi3 from 3.11 (nanobind's linked mode needs 3.12 for
  that) and needs no C++ or extra build dependency.
- WASI is hand-written C in the module (see "Design: WASI"): not a shim in Python, and not an existing C implementation (uvwasi, which WABT uses
  itself for `wasm-interp`, was named here as the option if WASI came back; what was decided instead is header-only C compiled into the module, so
  that a built module needs nothing at run time).
- **The configuration of WASI (`wasi=`).** One rule: every part of the world of the program has a default, given by the extension itself (C,
  compiled into the module), and the user may replace any of it. What needs no Python is plain C (the clocks, the random bytes, sleeping in
  `poll_oneoff`, the arguments, an empty environment, the files of POSIX); what needs the interpreter is C through `Python.h` (`sys.stdout` and
  the other standard streams, the exception of `proc_exit`, the files of Windows); only what cannot be guessed comes from the user (which
  directories, which addresses). Nothing is required of the user, and only the call can configure it (not the build, at least in the alpha).
  The form is a plain `dict`: an absent key is the default, an explicit `None` is *nothing* (arguments: none; output: thrown away; input:
  empty; files: none), so the two never mean the same. The default is worked out in C when it is used (a stream is `sys.stdout` *of that
  moment*, so a capture in a test or a notebook sees it): no Python object, class or factory is part of the built module, and a built module
  needs nothing of wasmext, nor of any other package, when it runs. `wasi=` is typed only in the `.pyi`, as a `TypedDict` with
  `NotRequired[...]` keys, the same for every module that uses WASI whatever it imports (the imports say which calls a module *can* make, not
  what it needs; a key the module does not use is accepted and ignored, an unknown key is a `TypeError`). Streams are typed with
  `_typeshed.SupportsRead[bytes]` and `SupportsWrite[bytes]` (output may also be a `Callable[[bytes], object]`), not with protocols of our own.
  Nothing is `Required`. Every other part of the program's world is replaced the same way: through a key (`clock`: id of the clock ->
  nanoseconds, `random`: how many -> that many bytes; neither takes `None`, which would mean a clock that stands still), or call by call
  through `imports`. A text stream (sys.stdout, a `StringIO`) given explicitly works as the default does: it gets the bytes through its
  binary side, after its text layer is flushed, or as text where it has none.
  *Built:* all of the above, and the end of the program (below).
- **The end of a program.** `proc_exit` and `proc_raise` end it, as on the operating system: the exception carries the code or the signal
  (`WasiExit`, `WasiSignal`, with a common base), the C closes at once every descriptor the program opened (files, directories and, when
  they are there, sockets; not what belongs to the user: `sys.stdout`, a stream the caller gave, the directories of the preopens are
  flushed, not closed), the instance is marked finished, and a call into it afterwards raises an error that says so. A trap ends the
  program too, but only a command (a module that exports `_start`): the trap of a function of a library is a trap, and the instance goes on. (A command
  is called once by the specification; this replaces "the instance stays usable after `proc_exit`".) *Built.* What the exception says of the signal: `.signal` is
  the number in WASI 0.1 and `.name` is `SIGABRT` and so on; the signals that would not end a process (none, the child, continue, stop and the stops of a
  terminal, urgent data, the window size) are answered with success and the program goes on. The stub: `WasiTerminated`, `WasiExit`, `WasiSignal`.
- **Sockets: postponed.** The idea (addresses to listen on in `wasi=`, the sockets made in C, handed to the program as descriptors after the
  preopened directories, for `sock_accept`, `sock_recv`, `sock_send`, `sock_shutdown`; no connecting out, the first snapshot has no call for it) was
  not built, for want of anything to compare it to: the preview1 of today's wasmtime (`crates/wasi/src/p1.rs`) has no sockets ("sockets are not
  currently supported"), `--tcplisten` of its CLI is "experimental, legacy wasip1 implementation only" (how that one numbered the descriptors was not
  found out), and the official test suite has no test of sockets for WASI 0.1 (those it has are for 0.3). The design would be ours alone, and a public
  interface that nothing checks. The four `sock_*` stay `ENOTSOCK`. To be taken up when a program needs them.
- **`poll_oneoff` waits on the realtime and the monotonic clock only.** The clocks of the process and of the thread (CPU time) are not built: the specification of the first snapshot does not say what it means to wait for a CPU clock, which does not advance while the program waits, so there is no behaviour to implement or to check against (the official tests do not ask for one). A subscription to them is answered at once with `EINVAL` in its event (`wasi_subscription_wait`), not a hang. To be taken up if the specification or a program gives a meaning.
- **C first: the layers do not depend on `Python.h`; only the exports of the module and the hooks do (the direction is decided, nothing of
  it is built).** Four layers, each knowing only those below it:
  1. the C of `wasm2c` (already plain C: the instance, the exports as C functions, the imports as C functions, the memory);
  2. the **core of the glue**, plain C: the life of an instance, the traps (`setjmp`), the table of the imports (`h->lf[]`, `h->li[]`), the
     export record of the link (`wasmext_export` is a C struct already: the capsule `wasmext.export.v1` is only how Python carries the
     pointer), memory and tables as C views;
  3. the **core of WASI** (`wasi_core.h`), plain C: the table of descriptors, the walk of paths (`openat`; a native path for Windows),
     arguments, environment, clocks, random bytes, `poll_oneoff`, the end of a program. Whatever needs the world outside it is a **hook**
     (a table of function pointers the host fills in): reading and writing the standard streams, a function that replaces a clock or the random
     bytes, the report of an error, the end of a program (`proc_exit`, `proc_raise`), the check that the host wants to interrupt a sleep;
  4. the **Python layer** (needs `Python.h`): the types `Instance` and `Memory`, the methods of the exports (the conversion of arguments and
     results), the imports given as Python callables, the memory as a `memoryview`, the exceptions (`Trap`, `LinkError`, `WasiExit`,
     `WasiSignal`), the dict `wasi=` turned into the configuration of the core, the capsule, and the **implementation of the hooks** with the
     Python API (`sys.stdout`, an object with `write`, the exceptions, `PyErr_CheckSignals`).
  What it is for: the same layers 1 to 3 give a **shared library** (`.so`/`.dll`: a module with a C API for `ctypes`/`cffi`, Rust, Go, with no
  Python in it) and a **C runner** (`wasmext-run module.wasm`) that runs the official WASI test suite with no Python in between (the suite is
  run through a Python adapter now, which is what made the Windows job slow), as well as the extension for CPython that the project is for.
  A third product of the same layers, no Python at all: a **native executable** of a WASI program (`wasmext natify --exe` is the idea): the C of
  `wasm2c`, the core of the glue, the core of WASI with the hooks filled in plain C (the standard streams are descriptors 0, 1, 2; `proc_exit`
  is `exit`; a signal is `raise`), and a `main()` that gives the arguments and the environment of the process to the program and calls
  `_start`. With it `lua.wasm`, `qjs.wasm` or `coreutils.wasm` become ordinary command line programs, built by the C compiler of the machine;
  the C runner of the test suite is the same thing with a path to the file in place of a built-in module.
  Where it stands now: in `wasi_common.h` (2860 lines) 49 of the 135 functions mention Python (stdio through `sys.stdout`, the configuration, the
  exceptions, the files of Windows through `os`, the user functions for the clock and the random bytes); the rest is plain C already. The
  files of Windows are the last place where the core needs the interpreter for data, which is why the native path to files on Windows
  (the plan, item 9) and this split are one piece of work from two sides. The first step is the split of the WASI header, not of the whole
  glue, and it comes when something needs a host that is not Python (the runner, a shared library); the Python layer stays as it is, and the
  hooks are `static inline` so that the split costs no call (to be measured). The contract of the link between two instances keeps its form;
  a C host would carry the same record in its own way.
  **The layers of the glue and of WASI, as files (a proposal, not decided; nothing built).** Today the generator (`_gen.py`) writes the glue of a
  module as one `.c`, from Python string templates; of the 245 lines it writes for `simple.wasm`, 16 mention the module or the export, the other 230
  are the same for every module (the traps, `set_trap_error`, the `wasmext_export` record and its layout fingerprint, the signals, the machinery of
  `Instance`). The files that the layers of "C first" would become, the inner ones nested and the outer ones side by side on the same core:
  1. `wasmext_glue.h`, the glue that is the same for every module, **no `Python.h`**: the traps, the export record and its fingerprint, the
     signals, the table of hooks. Shipped and copied beside the C of the module, as `wasi_core.h` is.
  2. `<name>_glue.h`, the glue of the module, generated, **no `Python.h`**: for each export a typed C function (as `link_call0` in the glue
     today: `result f(void *instance, parameters..., int *trapped)`), the tables of exports, imports, memories and globals with their signature strings,
     the instantiation and the release.
  3. The front ends, each on 1 and 2:
     a. `<name>_py.c`, generated, **with `Python.h`**: the type `Instance`, the wrappers of the exports (they parse the Python arguments and call
        the typed function of 2 in the same translation unit: no packing of values), the table of methods, the init of the module. It is the one
        `.c` that the build compiles for the extension for CPython (so no fixed stub is needed);
     b. a shared library: a fixed `.c` that exports the functions of 2 as symbols, **and a generated ctypes wrapper** (`<name>_ctypes.py`, with a
        `.pyi`): it loads the `.so`/`.dll`, sets `argtypes`/`restype` from the signature strings, and gives a class `Instance` with the same
        methods. **The wrapper has the same interface as `Instance` of the extension** (decided): the same methods and attributes, the same arguments,
        `imports` as Python callables, `wasi={...}` as the same dict, `__exports__`, the memory as a `memoryview`, the same exceptions (`Trap`,
        `LinkError`, `WasiExit`, `WasiSignal`), so that code and the `.pyi` are the same for both (one stub, not two). The wheel then depends on the
        platform and not on the version of Python; it may serve interpreters with no CPython extensions (PyPy, GraalPy: **not tried**). A call through
        ctypes costs much more than a call of the extension: an alternative, not a replacement. **The error of a host function is settled by the protocol
        below** (it was the one that looked like a block). Still open when it is built: the interruption of a sleep (`PyErr_CheckSignals` has no
        place in the core: a hook; a `KeyboardInterrupt` that comes while a callback runs is caught inside it, like any exception); the link between
        two instances (the capsule `wasmext.export.v1` is a CPython object: a pointer to the record would be carried by the wrapper in its own way,
        and whether an extension and a ctypes instance can link with each other is open); the GIL (ctypes releases it during a call of a function of
        a `CDLL`); the `CFUNCTYPE` objects of the imports kept alive as long as the instance;
     c. an executable: a `.c` with `main()` that gives the arguments and the environment of the process to the program, the hooks of WASI in plain C
        (standard streams are descriptors 0, 1, 2; `proc_exit` is `exit`; a signal is `raise`), and calls `_start` (`natify --exe`).
  WASI follows the same cut: `wasi_core.h` (plain C: descriptors, the walk of paths, arguments, environment, clocks, random bytes, `poll_oneoff`, the
  end of a program; whatever needs the world outside it is a hook, a table of function pointers) and, for each host, its hooks: `wasi_python.h`
  (with `Python.h`: `sys.stdout` and objects with `write`, the dict `wasi=` turned into the configuration, the exceptions `WasiExit` and `WasiSignal`,
  the user functions for the clock and the random bytes), the hooks in plain C of the executable, and for the shared library the hooks that the
  ctypes wrapper gives as callbacks. The native path to files on Windows (the plan, item 9) is the last thing that keeps the core from being free of
  the interpreter.
  *A uniform thunk instead of the typed wrapper* (a function of one form that the Python layer calls with the values packed by the signature
  string) was thought of and measured with a prototype: +4.2 ns on a call of 40 ns (median), +5 % by the best rounds, within the noise. It is not
  needed in this scheme (3a calls the typed function of 2 directly) and is kept here only as the measurement.

- `wasmhost` is a different tool (a facade over engines); its API is a guide for names and errors, the reference for behaviour
  is the specification and the JavaScript API.
