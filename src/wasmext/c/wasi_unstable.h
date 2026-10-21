/* WASI 0.1, `wasi_unstable` (the first snapshot, "preview0"): the calls are those of wasi_core.h, named `wasi_<name>`, except
   those that read or write what differs from `wasi_snapshot_preview1` (see wasi_core.h), which are `wasi_unstable_<name>` and
   are defined here. `sock_accept` is not a call of this snapshot. */
#ifndef WASMEXT_WASI_UNSTABLE_H
#define WASMEXT_WASI_UNSTABLE_H

#include "wasi_core.h"

/* the order of whence in this snapshot: cur, end, set */
static inline uint32_t wasi_unstable_fd_seek(void *s, uint32_t fd, uint64_t offset, uint32_t whence, uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    static const int native[3] = {SEEK_CUR, SEEK_END, SEEK_SET};
    if (whence > 2) return WASI_E_INVAL;
    return wasi_seek_native(w, fd, (int64_t)offset, native[whence], ptr, WASI_R_FD_SEEK);
}

/* the filestat of this snapshot has a 32-bit link count (56 bytes) */
static inline uint32_t wasi_unstable_fd_filestat_get(void *s, uint32_t fd, uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    return wasi_filestat_of_fd(w, fd, ptr, 1, trapped);
}

static inline uint32_t wasi_unstable_path_filestat_get(void *s, uint32_t fd, uint32_t flags, uint32_t path, uint32_t len,
                                                       uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    return wasi_filestat_of_path(w, fd, flags, path, len, ptr, 1, trapped);
}

/* the clock subscription of this snapshot starts with an identifier (the subscriptions are 56 bytes) */
static inline uint32_t wasi_unstable_poll_oneoff(void *s, uint32_t in, uint32_t out, uint32_t count, uint32_t nevents,
                                                 int *trapped) {
    WASI_STATE(s);
    return wasi_poll(w, in, out, count, nevents, 1, trapped);
}

#endif
