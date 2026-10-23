# WASI 0.1 compared with uvwasi (2026-10-23)

uvwasi (Node.js; WABT's `wasm-interp` uses it) is an older implementation of the same specification, tested for years. It is **not** used here: the WASI of wasmext is header-only C in the module, with
nothing to link (see "Design: WASI" in [DESIGN.md](DESIGN.md); the question of using libuv is at the end of this file). It is used as a **reference for behaviour**: its logic was read against `wasi_core.h`
(and `wasi_python.h`), call by call, in four parts (rights and the table of descriptors; paths; descriptor I/O and directories; polling, clocks, errors), uvwasi at `fe602a6` (WABT pins `55eff19`).
Everything below is **reading** of both sources unless it says tested; the fixes have tests that fail on the old code.

## Fixed

- **A way out of the preopen (security).** A slash after the last name makes the kernel follow a link there whatever `O_NOFOLLOW` says, so `path_open(dirfd, 0, "link/", O_DIRECTORY)` (and `path_filestat_get`,
  `path_readlink`) with `link` pointing out of the preopen opened the directory outside it. Tested on the system call and in all three builds of WASI 0.1 (native, Python files, ctypes); the same walk was in the new
  WASI 0.2 `filesystem` (Python and C). Now a link with a slash and no `symlink_follow` is `NOTDIR` (the walk reads the link before it hands the name over). uvwasi does not have this one (it never uses
  `O_NOFOLLOW`); in return it follows **intermediate** links in the system without a check, which ours does not (the walk opens each directory with `O_NOFOLLOW`). `test_a_slash_after_a_link_does_not_lead_out`.
  The Windows backend (`wasi_files_win32.h`) cuts the slash off by itself and was not changed or tested here. What is left of this class is the race that every walk by name has (the tree changed under the walk by another process).
- **`poll_oneoff`** reported every descriptor ready at once. Now a pipe, a FIFO, a terminal, a socket and the standard input (when no hook stands in for it) are asked of the system with `poll`; the call waits for them
  and the clocks together; `nbytes` is `FIONREAD`; a hangup is `fd_readwrite_hangup`. A subscription needs `poll_fd_readwrite` and `fd_read`/`fd_write` (the event says `NOTCAPABLE`). A stream that goes through a hook (Python's `sys.stdin`) cannot be asked and
  stays ready at once. Not changed on Windows.
- **`fd_read` into several buffers** went on to the next buffer after a full one, which blocks on a pipe although something was read; now it stops after the first full buffer unless the descriptor is a regular file.
- **The errno table:** 27 errnos were mapped and the rest were `EIO`; now all 76 names of the specification (`ENOTTY`, `ENXIO`, `ETXTBSY`, `EDQUOT`, `EOVERFLOW`, `ECONNREFUSED`, ...), the ones a system lacks guarded. `tests/test_wasi_errno.py`.
- **The standard streams** said they were a character device whatever they were, so wasi-libc's `isatty` was true for a redirected stream. Now a stream that is the process's own descriptor says what it is (a pipe is unknown, a file is regular, with the real `filestat`); a hooked one stays a character device.
- **`path_readlink` with a buffer of 0 bytes** was `EINVAL`; it is success with nothing written (a file is still `EINVAL`).
- **The mode of an open** follows the rights that need writing (`fd_write`, `fd_datasync`, `fd_allocate`, `fd_filestat_set_size`), as in uvwasi; wasi-libc leaves these out of a read-only open.
- **`fd_advise`** needs its right and a known advice (`EINVAL` above 5). **`fd_close` of a standard stream** frees the number (the stream of the host stays open). **`fd_fdstat_set_rights`** on a standard stream accepts the same or less.
- **A bad buffer in the middle of the buffers** no longer leaves the data before it written with `EFAULT` and no count; a write to a standard stream that fails after something was written reports what was written.
- **`fd_allocate`** reserves space (`posix_fallocate`, so `ENOSPC` is possible, and a pipe is `ESPIPE`); **`random_get`** uses `getrandom` and does not need `/dev/urandom` (a chroot, no descriptors left).

## Left as it is, on purpose

- `path_open` **cuts the rights** it was asked for to those the directory can pass on instead of `NOTCAPABLE` (uvwasi refuses). Go and others ask for rights of directories that include writing, so the strict form would break
  opening a directory in a read-only preopen. wasi-libc masks the rights itself, so it is not affected either way.
- `fd_pread`/`fd_pwrite` do not need `fd_seek` (uvwasi asks for it; wasi-libc opens for writing without it). `fd_prestat_get` of a descriptor that is no preopen is `BADF` (uvwasi: `EINVAL`; wasi-libc stops its scan at `BADF`).
- A preopen reports the rights to read and write (uvwasi gives directory rights only); the order of the checks is the type first, then the right (uvwasi: the right first).
- `poll_oneoff`: an absolute timeout is counted on the subscribed clock (uvwasi counts on the real-time clock whatever it is), clocks 2 and 3 are `EINVAL`, every clock that is due makes an event (uvwasi: one).
- Ours is better than uvwasi in: `fd_fdstat_get` flags (uvwasi shows `fcntl` flags), the times in nanoseconds (uvwasi cuts to seconds), `fd_readdir` (real inode numbers, `.` and `..`), the checks of `args_get`/`environ_get`.
- `path_symlink` to an absolute target is `NOTCAPABLE` (uvwasi: `EPERM`); `fd_prestat_dir_name` with a short buffer is `NAMETOOLONG` (uvwasi: `ENOBUFS`).

## Not compared / open

The Windows backend; the first snapshot (`wasi_unstable`) beyond what the shared code does; `sock_*` (uvwasi has real ones on sockets it was given, ours say `NOTSOCK`).
Not covered by the official `wasi-testsuite` (as far as the reading says): the slash after a link, `poll_oneoff` on pipes, the multi-buffer read, `fd_advise`, the errno table, the type of a redirected stream.

## Why not libuv (or uvwasi) inside

- **No dependency in a built module.** The module, extension or program needs nothing at run time; libuv would be built and linked into every wheel on every system (Linux, macOS, Windows, Pyodide, Android).
- **libuv has no calls relative to a directory descriptor** (`openat`, `fstatat`, `linkat`...). A capability system such as WASI maps onto exactly those; uvwasi has to resolve paths by name itself, and that is where it
  differs: it checks the path lexically and lets the system follow links in the middle, which can lead out (the walk here opens each directory with `O_NOFOLLOW` instead).
- **libuv's file API loses what WASI says**: times in seconds, flags of its own, readdir without `.`/`..`.
- **An event loop** (its own initialisation, signal handling, thread pool) is more than synchronous calls need, and sits badly inside a Python extension that is loaded by other things.
- What libuv would give is what this comparison found missing: a long-tested table of errors, polling of pipes, portability to rare systems. That is a reason to compare with it, as done here, and to take its tests as a guide.
