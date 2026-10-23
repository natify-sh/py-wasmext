/* wasi:cli (13 imports): environment, exit, stdin, stdout, stderr and the terminals (the twin of p2/wasi_p2_cli.py, where the layouts are described).
 *
 * environment: `s->args`, `s->env_names`/`env_values`, `s->initial_cwd` (owned by the caller). exit: `s->exit` is told the code; by default it records `exited` and `exit_code`
 * and traps. The standard streams: `s->std[i]` (a wasi_p2_stream) or, by default, the descriptors 0, 1 and 2 of the process, made when first asked for; a handle to a
 * standard stream is a new handle every time, to the same stream, and dropping it closes nothing. Terminals: `s->terminals` says which are, the resources have no methods. */
#ifndef WASI_P2_CLI_H
#define WASI_P2_CLI_H

#include "wasi_p2_io.h"
#ifdef _WIN32
#include <io.h>
#else
#include <errno.h>
#include <poll.h>
#include <unistd.h>
#endif

#define WASI_P2_STD_CHUNK 4096u

/* a stream over a descriptor of the process */
typedef struct {
    wasi_p2_stream base;
    int fd;
} wasi_p2_fd_stream;

WASI_P2_FN int wasi_p2_fd_ready_in(wasi_p2_state *s, wasi_p2_stream *st) {
    (void)s;
#ifdef _WIN32
    (void)st;
    return 1;
#else
    struct pollfd p = {((wasi_p2_fd_stream *)st)->fd, POLLIN, 0};
    return poll(&p, 1, 0) > 0;
#endif
}

WASI_P2_FN int wasi_p2_fd_read(wasi_p2_state *s, wasi_p2_stream *st, uint8_t *buf, uint64_t len, uint64_t *got) {
    wasi_p2_fd_stream *f = (wasi_p2_fd_stream *)st;
    *got = 0;
    if (len == 0 || !wasi_p2_fd_ready_in(s, st)) return WASI_P2_STREAM_OK;
#ifdef _WIN32
    int n = _read(f->fd, buf, (unsigned)len);
#else
    ssize_t n = read(f->fd, buf, (size_t)len);
#endif
    if (n < 0) {
        st->failure = "read failed";
        return WASI_P2_STREAM_FAILED;
    }
    if (n == 0) return WASI_P2_STREAM_CLOSED;
    *got = (uint64_t)n;
    return WASI_P2_STREAM_OK;
}

WASI_P2_FN uint64_t wasi_p2_fd_check_write(wasi_p2_state *s, wasi_p2_stream *st, int *status) {
    (void)s, (void)st;
    *status = WASI_P2_STREAM_OK;
    return WASI_P2_STD_CHUNK;
}

WASI_P2_FN int wasi_p2_fd_write(wasi_p2_state *s, wasi_p2_stream *st, const uint8_t *data, uint64_t len) {
    wasi_p2_fd_stream *f = (wasi_p2_fd_stream *)st;
    (void)s;
    while (len) {
#ifdef _WIN32
        int n = _write(f->fd, data, (unsigned)len);
#else
        ssize_t n = write(f->fd, data, (size_t)len);
        if (n < 0 && errno == EINTR) continue;
#endif
        if (n <= 0) {
            st->failure = "write failed";
            return WASI_P2_STREAM_FAILED;
        }
        data += n;
        len -= (uint64_t)n;
    }
    return WASI_P2_STREAM_OK;
}

WASI_P2_FN int wasi_p2_fd_flush(wasi_p2_state *s, wasi_p2_stream *st) {
    (void)s, (void)st;
    return WASI_P2_STREAM_OK;
}

/* Streams on descriptors, owned by the caller (`free` them after the state): for the standard streams of a state, or for tests. */
WASI_P2_FN wasi_p2_fd_stream *wasi_p2_fd_input_new(wasi_p2_state *s, int fd) {
    wasi_p2_fd_stream *f = (wasi_p2_fd_stream *)calloc(1, sizeof *f);
    if (!f) s->trap(s, "out of memory");
    f->fd = fd;
    f->base.read = wasi_p2_fd_read;
    f->base.ready = wasi_p2_fd_ready_in;
    return f;
}

WASI_P2_FN wasi_p2_fd_stream *wasi_p2_fd_output_new(wasi_p2_state *s, int fd) {
    wasi_p2_fd_stream *f = (wasi_p2_fd_stream *)calloc(1, sizeof *f);
    if (!f) s->trap(s, "out of memory");
    f->fd = fd;
    f->base.check_write = wasi_p2_fd_check_write;
    f->base.write = wasi_p2_fd_write;
    f->base.flush = wasi_p2_fd_flush;
    f->base.ready = wasi_p2_always_ready;
    return f;
}

/* the standard stream i (0 stdin, 1 stdout, 2 stderr) */
WASI_P2_FN wasi_p2_stream *wasi_p2_std(wasi_p2_state *s, int i) {
    if (s->std[i]) return (wasi_p2_stream *)s->std[i];
    if (!s->std_default[i]) s->std_default[i] = i == 0 ? (void *)wasi_p2_fd_input_new(s, 0) : (void *)wasi_p2_fd_output_new(s, i);
    return (wasi_p2_stream *)s->std_default[i];
}

/* environment */

WASI_P2_FN void wasi_cli_environment_get_environment(wasi_p2_state *s, uint32_t comp, uint32_t retptr) {
    uint32_t ptr = wasi_p2_alloc(s, comp, 4, 16 * s->env_count);
    for (uint32_t i = 0; i < s->env_count; i++) {
        wasi_p2_string(s, comp, s->env_names[i], ptr + 16 * i);
        wasi_p2_string(s, comp, s->env_values[i], ptr + 16 * i + 8);
    }
    wasi_p2_store_u32(s, comp, retptr, ptr);
    wasi_p2_store_u32(s, comp, retptr + 4, s->env_count);
}

WASI_P2_FN void wasi_cli_environment_get_arguments(wasi_p2_state *s, uint32_t comp, uint32_t retptr) {
    uint32_t ptr = wasi_p2_alloc(s, comp, 4, 8 * s->arg_count);
    for (uint32_t i = 0; i < s->arg_count; i++) wasi_p2_string(s, comp, s->args[i], ptr + 8 * i);
    wasi_p2_store_u32(s, comp, retptr, ptr);
    wasi_p2_store_u32(s, comp, retptr + 4, s->arg_count);
}

WASI_P2_FN void wasi_cli_environment_initial_cwd(wasi_p2_state *s, uint32_t comp, uint32_t retptr) {
    if (!s->initial_cwd) {
        wasi_p2_store_u8(s, comp, retptr, 0);
        return;
    }
    wasi_p2_string(s, comp, s->initial_cwd, retptr + 4);
    wasi_p2_store_u8(s, comp, retptr, 1);
}

/* exit */

WASI_P2_FN void wasi_cli_exit_exit(wasi_p2_state *s, uint32_t status) { s->exit(s, status == 0 ? 0 : 1); }

WASI_P2_FN void wasi_cli_exit_exit_with_code(wasi_p2_state *s, uint32_t status_code) { s->exit(s, status_code & 0xFF); }

/* the standard streams: a handle that does not close the stream when dropped */

WASI_P2_FN uint32_t wasi_cli_stdin_get_stdin(wasi_p2_state *s) {
    return wasi_p2_table_new(s, WASI_P2_KIND_INPUT_STREAM, wasi_p2_std(s, 0), NULL);
}
WASI_P2_FN uint32_t wasi_cli_stdout_get_stdout(wasi_p2_state *s) {
    return wasi_p2_table_new(s, WASI_P2_KIND_OUTPUT_STREAM, wasi_p2_std(s, 1), NULL);
}
WASI_P2_FN uint32_t wasi_cli_stderr_get_stderr(wasi_p2_state *s) {
    return wasi_p2_table_new(s, WASI_P2_KIND_OUTPUT_STREAM, wasi_p2_std(s, 2), NULL);
}

/* the terminals */

WASI_P2_FN void wasi_p2_terminal(wasi_p2_state *s, uint32_t comp, uint32_t retptr, unsigned bit, uint32_t kind) {
    if (s->terminals & bit) {
        wasi_p2_store_u8(s, comp, retptr, 1);
        wasi_p2_store_u32(s, comp, retptr + 4, wasi_p2_table_new(s, kind, NULL, NULL));
    } else {
        wasi_p2_store_u8(s, comp, retptr, 0);
    }
}

WASI_P2_FN void wasi_cli_terminal_stdin_get_terminal_stdin(wasi_p2_state *s, uint32_t comp, uint32_t retptr) {
    wasi_p2_terminal(s, comp, retptr, WASI_P2_TERMINAL_STDIN, WASI_P2_KIND_TERMINAL_INPUT);
}
WASI_P2_FN void wasi_cli_terminal_stdout_get_terminal_stdout(wasi_p2_state *s, uint32_t comp, uint32_t retptr) {
    wasi_p2_terminal(s, comp, retptr, WASI_P2_TERMINAL_STDOUT, WASI_P2_KIND_TERMINAL_OUTPUT);
}
WASI_P2_FN void wasi_cli_terminal_stderr_get_terminal_stderr(wasi_p2_state *s, uint32_t comp, uint32_t retptr) {
    wasi_p2_terminal(s, comp, retptr, WASI_P2_TERMINAL_STDERR, WASI_P2_KIND_TERMINAL_OUTPUT);
}
WASI_P2_FN void wasi_cli_terminal_input_terminal_input_drop(wasi_p2_state *s, uint32_t handle) {
    wasi_p2_table_drop(s, handle, WASI_P2_KIND_TERMINAL_INPUT);
}
WASI_P2_FN void wasi_cli_terminal_output_terminal_output_drop(wasi_p2_state *s, uint32_t handle) {
    wasi_p2_table_drop(s, handle, WASI_P2_KIND_TERMINAL_OUTPUT);
}

#endif /* WASI_P2_CLI_H */
