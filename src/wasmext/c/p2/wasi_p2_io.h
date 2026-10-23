/* wasi:io (23 imports): error, poll and streams (the twin of p2/wasi_p2_io.py; the layouts of the results are described there).
 *
 * A stream of the host is a `wasi_p2_stream` with the functions it needs (an input stream: read; an output stream: check_write, write, flush); `ready` is for pollables.
 * `read` and the others return WASI_P2_STREAM_OK, WASI_P2_STREAM_CLOSED (the end) or WASI_P2_STREAM_FAILED (then `failure` is the message). A write of more than
 * check_write allows is a trap. `wasi_p2_memory_input` and `wasi_p2_buffer_output` are here; files and sockets come with their packages. */
#ifndef WASI_P2_IO_H
#define WASI_P2_IO_H

#include "wasi_p2_clocks.h" /* the deadline pollables share the table and wasi_p2_free_obj */

#define WASI_P2_READ_CAP 65536u

enum { WASI_P2_STREAM_OK = 0, WASI_P2_STREAM_CLOSED = 1, WASI_P2_STREAM_FAILED = 2 };

typedef struct wasi_p2_stream {
    int (*read)(wasi_p2_state *s, struct wasi_p2_stream *st, uint8_t *buf, uint64_t len, uint64_t *got);
    uint64_t (*check_write)(wasi_p2_state *s, struct wasi_p2_stream *st, int *status);
    int (*write)(wasi_p2_state *s, struct wasi_p2_stream *st, const uint8_t *data, uint64_t len);
    int (*flush)(wasi_p2_state *s, struct wasi_p2_stream *st);
    int (*ready)(wasi_p2_state *s, struct wasi_p2_stream *st);
    void (*destroy)(wasi_p2_state *s, struct wasi_p2_stream *st); /* when the handle is dropped; may be NULL */
    const char *failure;
    int failure_has_code, failure_code; /* the error-code of wasi:filesystem, when the failure came from a file */
    void *ctx;
} wasi_p2_stream;

/* the `error` resource: a code (-1: none) and the message */
typedef struct {
    int code;
    char message[1];
} wasi_p2_error;

/* making resources for the guest */

WASI_P2_FN uint32_t wasi_p2_error_new_code(wasi_p2_state *s, const char *message, int code) {
    size_t n = strlen(message) + 1;
    wasi_p2_error *e = (wasi_p2_error *)malloc(sizeof *e + n);
    if (!e) s->trap(s, "out of memory");
    e->code = code;
    memcpy(e->message, message, n);
    return wasi_p2_table_new(s, WASI_P2_KIND_ERROR, e, wasi_p2_free_obj);
}

WASI_P2_FN uint32_t wasi_p2_error_new(wasi_p2_state *s, const char *message) { return wasi_p2_error_new_code(s, message, -1); }

WASI_P2_FN void wasi_p2_stream_destroy(wasi_p2_state *s, void *obj) {
    wasi_p2_stream *st = (wasi_p2_stream *)obj;
    if (st->destroy) st->destroy(s, st);
}

WASI_P2_FN uint32_t wasi_p2_input_stream_new(wasi_p2_state *s, wasi_p2_stream *st) {
    return wasi_p2_table_new(s, WASI_P2_KIND_INPUT_STREAM, st, wasi_p2_stream_destroy);
}

WASI_P2_FN uint32_t wasi_p2_output_stream_new(wasi_p2_state *s, wasi_p2_stream *st) {
    return wasi_p2_table_new(s, WASI_P2_KIND_OUTPUT_STREAM, st, wasi_p2_stream_destroy);
}

/* a stream over bytes it was given (not copied; they must outlive the stream) */
typedef struct {
    wasi_p2_stream base;
    const uint8_t *data;
    uint64_t len, pos;
} wasi_p2_memory_input;

WASI_P2_FN int wasi_p2_memory_input_read(wasi_p2_state *s, wasi_p2_stream *st, uint8_t *buf, uint64_t len, uint64_t *got) {
    wasi_p2_memory_input *m = (wasi_p2_memory_input *)st;
    (void)s;
    if (m->pos >= m->len && len) return WASI_P2_STREAM_CLOSED;
    uint64_t n = m->len - m->pos < len ? m->len - m->pos : len;
    memcpy(buf, m->data + m->pos, (size_t)n);
    m->pos += n;
    *got = n;
    return WASI_P2_STREAM_OK;
}

WASI_P2_FN int wasi_p2_always_ready(wasi_p2_state *s, wasi_p2_stream *st) {
    (void)s;
    (void)st;
    return 1;
}

WASI_P2_FN void wasi_p2_stream_free(wasi_p2_state *s, wasi_p2_stream *st) {
    (void)s;
    free(st);
}

WASI_P2_FN uint32_t wasi_p2_memory_input_new(wasi_p2_state *s, const uint8_t *data, uint64_t len) {
    wasi_p2_memory_input *m = (wasi_p2_memory_input *)calloc(1, sizeof *m);
    if (!m) s->trap(s, "out of memory");
    m->base.read = wasi_p2_memory_input_read;
    m->base.ready = wasi_p2_always_ready;
    m->base.destroy = wasi_p2_stream_free;
    m->data = data;
    m->len = len;
    return wasi_p2_input_stream_new(s, &m->base);
}

/* a stream that collects what is written (up to `limit` bytes in all); freed with the state, read `buf` and `len` before that */
typedef struct {
    wasi_p2_stream base;
    uint8_t *buf;
    uint64_t len, capacity, limit;
} wasi_p2_buffer_output;

WASI_P2_FN uint64_t wasi_p2_buffer_output_check_write(wasi_p2_state *s, wasi_p2_stream *st, int *status) {
    wasi_p2_buffer_output *b = (wasi_p2_buffer_output *)st;
    (void)s;
    *status = WASI_P2_STREAM_OK;
    return b->limit - b->len;
}

WASI_P2_FN int wasi_p2_buffer_output_write(wasi_p2_state *s, wasi_p2_stream *st, const uint8_t *data, uint64_t len) {
    wasi_p2_buffer_output *b = (wasi_p2_buffer_output *)st;
    if (b->len + len > b->capacity) {
        uint64_t cap = b->capacity ? b->capacity : 64;
        while (cap < b->len + len) cap *= 2;
        uint8_t *grown = (uint8_t *)realloc(b->buf, (size_t)cap);
        if (!grown) s->trap(s, "out of memory");
        b->buf = grown;
        b->capacity = cap;
    }
    if (len) memcpy(b->buf + b->len, data, (size_t)len);
    b->len += len;
    return WASI_P2_STREAM_OK;
}

WASI_P2_FN int wasi_p2_buffer_output_flush(wasi_p2_state *s, wasi_p2_stream *st) {
    (void)s;
    (void)st;
    return WASI_P2_STREAM_OK;
}

WASI_P2_FN int wasi_p2_buffer_output_ready(wasi_p2_state *s, wasi_p2_stream *st) {
    int status;
    return wasi_p2_buffer_output_check_write(s, st, &status) > 0;
}

/* the buffer is released by the caller with `wasi_p2_buffer_output_release` after the handle is dropped or the state freed */
WASI_P2_FN wasi_p2_buffer_output *wasi_p2_buffer_output_new(wasi_p2_state *s, uint64_t limit, uint32_t *handle) {
    wasi_p2_buffer_output *b = (wasi_p2_buffer_output *)calloc(1, sizeof *b);
    if (!b) s->trap(s, "out of memory");
    b->base.check_write = wasi_p2_buffer_output_check_write;
    b->base.write = wasi_p2_buffer_output_write;
    b->base.flush = wasi_p2_buffer_output_flush;
    b->base.ready = wasi_p2_buffer_output_ready;
    b->limit = limit;
    *handle = wasi_p2_output_stream_new(s, &b->base);
    return b;
}

WASI_P2_FN void wasi_p2_buffer_output_release(wasi_p2_buffer_output *b) {
    free(b->buf);
    free(b);
}

/* results */

WASI_P2_FN void wasi_p2_ok(wasi_p2_state *s, uint32_t comp, uint32_t retptr) { wasi_p2_store_u8(s, comp, retptr, 0); }

/* err(stream-error): the tag of the result at retptr, the variant at error_at */
WASI_P2_FN void wasi_p2_stream_err(wasi_p2_state *s, uint32_t comp, uint32_t retptr, uint32_t error_at, int status, wasi_p2_stream *st) {
    const char *failure = st->failure;
    wasi_p2_store_u8(s, comp, retptr, 1);
    if (status == WASI_P2_STREAM_FAILED) {
        wasi_p2_store_u8(s, comp, error_at, 0);
        wasi_p2_store_u32(s, comp, error_at + 4, wasi_p2_error_new_code(s, failure ? failure : "failed", st->failure_has_code ? st->failure_code : -1));
    } else {
        wasi_p2_store_u8(s, comp, error_at, 1);
    }
}

/* error */

WASI_P2_FN void wasi_io_error_error_to_debug_string(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    const char *message = ((wasi_p2_error *)wasi_p2_table_get(s, self, WASI_P2_KIND_ERROR)->obj)->message;
    uint32_t n = (uint32_t)strlen(message);
    uint32_t ptr = wasi_p2_alloc(s, comp, 1, n);
    if (n) memcpy(wasi_p2_mem(s, comp, ptr, n), message, n);
    wasi_p2_store_u32(s, comp, retptr, ptr);
    wasi_p2_store_u32(s, comp, retptr + 4, n);
}

WASI_P2_FN void wasi_io_error_error_drop(wasi_p2_state *s, uint32_t handle) { wasi_p2_table_drop(s, handle, WASI_P2_KIND_ERROR); }

/* poll */

WASI_P2_FN wasi_p2_pollable *wasi_p2_pollable_get(wasi_p2_state *s, uint32_t handle) {
    return (wasi_p2_pollable *)wasi_p2_table_get(s, handle, WASI_P2_KIND_POLLABLE)->obj;
}

WASI_P2_FN uint32_t wasi_io_poll_pollable_ready(wasi_p2_state *s, uint32_t self) {
    wasi_p2_pollable *p = wasi_p2_pollable_get(s, self);
    return (uint32_t)(p->ready(s, p) != 0);
}

WASI_P2_FN void wasi_io_poll_pollable_block(wasi_p2_state *s, uint32_t self) {
    wasi_p2_pollable *p = wasi_p2_pollable_get(s, self);
    while (!p->ready(s, p)) s->wait(s);
}

WASI_P2_FN void wasi_io_poll_pollable_drop(wasi_p2_state *s, uint32_t handle) { wasi_p2_table_drop(s, handle, WASI_P2_KIND_POLLABLE); }

/* Waits until one of the pollables is ready and gives the indexes of all that are (a list of u32). An empty list is a trap. */
WASI_P2_FN void wasi_io_poll_poll(wasi_p2_state *s, uint32_t comp, uint32_t in_ptr, uint32_t in_len, uint32_t retptr) {
    if (in_len == 0) s->trap(s, "poll of an empty list");
    wasi_p2_pollable **list = (wasi_p2_pollable **)malloc(in_len * sizeof *list);
    uint32_t *ready = (uint32_t *)malloc(in_len * sizeof *ready);
    if (!list || !ready) s->trap(s, "out of memory");
    for (uint32_t i = 0; i < in_len; i++) list[i] = wasi_p2_pollable_get(s, wasi_p2_load_u32(s, comp, in_ptr + 4 * i));
    uint32_t count = 0;
    for (;;) {
        for (uint32_t i = 0; i < in_len; i++)
            if (list[i]->ready(s, list[i])) ready[count++] = i;
        if (count) break;
        s->wait(s);
    }
    uint32_t ptr = wasi_p2_alloc(s, comp, 4, 4 * count);
    for (uint32_t k = 0; k < count; k++) wasi_p2_store_u32(s, comp, ptr + 4 * k, ready[k]);
    free(list);
    free(ready);
    wasi_p2_store_u32(s, comp, retptr, ptr);
    wasi_p2_store_u32(s, comp, retptr + 4, count);
}

/* streams */

WASI_P2_FN wasi_p2_stream *wasi_p2_input_get(wasi_p2_state *s, uint32_t handle) {
    return (wasi_p2_stream *)wasi_p2_table_get(s, handle, WASI_P2_KIND_INPUT_STREAM)->obj;
}

WASI_P2_FN wasi_p2_stream *wasi_p2_output_get(wasi_p2_state *s, uint32_t handle) {
    return (wasi_p2_stream *)wasi_p2_table_get(s, handle, WASI_P2_KIND_OUTPUT_STREAM)->obj;
}

/* Up to `len` bytes into a buffer from malloc (`*out`); when `block`, waits for at least one. Returns the status; the buffer is the caller's to free. */
WASI_P2_FN int wasi_p2_read(wasi_p2_state *s, wasi_p2_stream *st, uint64_t len, int block, uint8_t **out, uint64_t *got) {
    uint64_t n = len < WASI_P2_READ_CAP ? len : WASI_P2_READ_CAP;
    uint8_t *buf = (uint8_t *)malloc(n ? (size_t)n : 1);
    if (!buf) s->trap(s, "out of memory");
    for (;;) {
        *got = 0;
        int status = st->read(s, st, buf, n, got);
        if (status != WASI_P2_STREAM_OK || *got || !block || n == 0) {
            *out = buf;
            return status;
        }
        s->wait(s);
    }
}

WASI_P2_FN void wasi_p2_read_list(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t len, uint32_t retptr, int block) {
    wasi_p2_stream *st = wasi_p2_input_get(s, self);
    uint8_t *buf;
    uint64_t got;
    int status = wasi_p2_read(s, st, len, block, &buf, &got);
    if (status != WASI_P2_STREAM_OK) {
        free(buf);
        wasi_p2_stream_err(s, comp, retptr, retptr + 4, status, st);
        return;
    }
    uint32_t ptr = wasi_p2_alloc(s, comp, 1, (uint32_t)got);
    if (got) memcpy(wasi_p2_mem(s, comp, ptr, (uint32_t)got), buf, (size_t)got);
    free(buf);
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u32(s, comp, retptr + 4, ptr);
    wasi_p2_store_u32(s, comp, retptr + 8, (uint32_t)got);
}

WASI_P2_FN void wasi_p2_skip(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t len, uint32_t retptr, int block) {
    wasi_p2_stream *st = wasi_p2_input_get(s, self);
    uint8_t *buf;
    uint64_t got;
    int status = wasi_p2_read(s, st, len, block, &buf, &got);
    free(buf);
    if (status != WASI_P2_STREAM_OK) {
        wasi_p2_stream_err(s, comp, retptr, retptr + 8, status, st);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u64(s, comp, retptr + 8, got);
}

WASI_P2_FN void wasi_io_streams_input_stream_read(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t len, uint32_t retptr) {
    wasi_p2_read_list(s, comp, self, len, retptr, 0);
}
WASI_P2_FN void wasi_io_streams_input_stream_blocking_read(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t len, uint32_t retptr) {
    wasi_p2_read_list(s, comp, self, len, retptr, 1);
}
WASI_P2_FN void wasi_io_streams_input_stream_skip(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t len, uint32_t retptr) {
    wasi_p2_skip(s, comp, self, len, retptr, 0);
}
WASI_P2_FN void wasi_io_streams_input_stream_blocking_skip(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t len, uint32_t retptr) {
    wasi_p2_skip(s, comp, self, len, retptr, 1);
}

WASI_P2_FN int wasi_p2_stream_pollable_ready(wasi_p2_state *s, wasi_p2_pollable *p) {
    wasi_p2_stream *st = (wasi_p2_stream *)p->ctx;
    return st->ready ? st->ready(s, st) : 1;
}

WASI_P2_FN uint32_t wasi_p2_stream_pollable(wasi_p2_state *s, wasi_p2_stream *st) {
    wasi_p2_pollable *p = (wasi_p2_pollable *)calloc(1, sizeof *p);
    if (!p) s->trap(s, "out of memory");
    p->ready = wasi_p2_stream_pollable_ready;
    p->ctx = st;
    return wasi_p2_table_new(s, WASI_P2_KIND_POLLABLE, p, wasi_p2_free_obj);
}

WASI_P2_FN uint32_t wasi_io_streams_input_stream_subscribe(wasi_p2_state *s, uint32_t self) {
    return wasi_p2_stream_pollable(s, wasi_p2_input_get(s, self));
}

WASI_P2_FN void wasi_io_streams_input_stream_drop(wasi_p2_state *s, uint32_t handle) {
    wasi_p2_input_get(s, handle); /* a bad handle traps before anything is dropped */
    wasi_p2_table_drop(s, handle, WASI_P2_KIND_INPUT_STREAM);
}

WASI_P2_FN void wasi_io_streams_output_stream_check_write(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_stream *st = wasi_p2_output_get(s, self);
    int status = WASI_P2_STREAM_OK;
    uint64_t budget = st->check_write(s, st, &status);
    if (status != WASI_P2_STREAM_OK) {
        wasi_p2_stream_err(s, comp, retptr, retptr + 8, status, st);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u64(s, comp, retptr + 8, budget);
}

/* One write, limited by the budget (a bigger one traps); returns 0 and writes the error if it failed. */
WASI_P2_FN int wasi_p2_write(wasi_p2_state *s, uint32_t comp, wasi_p2_stream *st, const uint8_t *data, uint64_t len, uint32_t retptr) {
    int status = WASI_P2_STREAM_OK;
    uint64_t budget = st->check_write(s, st, &status);
    if (status == WASI_P2_STREAM_OK) {
        if (len > budget) s->trap(s, "write of more than check-write allows");
        status = st->write(s, st, data, len);
    }
    if (status != WASI_P2_STREAM_OK) {
        wasi_p2_stream_err(s, comp, retptr, retptr + 4, status, st);
        return 0;
    }
    return 1;
}

WASI_P2_FN void wasi_io_streams_output_stream_write(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t ptr, uint32_t len, uint32_t retptr) {
    wasi_p2_stream *st = wasi_p2_output_get(s, self);
    const uint8_t *data = wasi_p2_mem(s, comp, ptr, len);
    if (wasi_p2_write(s, comp, st, data, len, retptr)) wasi_p2_ok(s, comp, retptr);
}

/* Writes it all in pieces as the budget allows, waiting when it is 0, then flushes. `data` NULL means zeroes. */
WASI_P2_FN void wasi_p2_write_all_and_flush(wasi_p2_state *s, uint32_t comp, wasi_p2_stream *st, const uint8_t *data, uint64_t len, uint32_t retptr) {
    static const uint8_t zeroes[4096] = {0};
    int status = WASI_P2_STREAM_OK;
    while (len) {
        uint64_t budget = st->check_write(s, st, &status);
        if (status != WASI_P2_STREAM_OK) break;
        if (budget == 0) {
            s->wait(s);
            continue;
        }
        uint64_t n = len < budget ? len : budget;
        if (!data && n > sizeof zeroes) n = sizeof zeroes;
        status = st->write(s, st, data ? data : zeroes, n);
        if (status != WASI_P2_STREAM_OK) break;
        if (data) data += n;
        len -= n;
    }
    if (status == WASI_P2_STREAM_OK) status = st->flush(s, st);
    if (status != WASI_P2_STREAM_OK) {
        wasi_p2_stream_err(s, comp, retptr, retptr + 4, status, st);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
}

WASI_P2_FN void wasi_io_streams_output_stream_blocking_write_and_flush(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t ptr, uint32_t len,
                                                                       uint32_t retptr) {
    wasi_p2_stream *st = wasi_p2_output_get(s, self);
    wasi_p2_write_all_and_flush(s, comp, st, wasi_p2_mem(s, comp, ptr, len), len, retptr);
}

WASI_P2_FN void wasi_io_streams_output_stream_write_zeroes(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t len, uint32_t retptr) {
    wasi_p2_stream *st = wasi_p2_output_get(s, self);
    uint8_t *zeroes = (uint8_t *)calloc(len ? (size_t)len : 1, 1);
    if (!zeroes) s->trap(s, "out of memory");
    int ok = wasi_p2_write(s, comp, st, zeroes, len, retptr);
    free(zeroes);
    if (ok) wasi_p2_ok(s, comp, retptr);
}

WASI_P2_FN void wasi_io_streams_output_stream_blocking_write_zeroes_and_flush(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t len,
                                                                              uint32_t retptr) {
    wasi_p2_write_all_and_flush(s, comp, wasi_p2_output_get(s, self), NULL, len, retptr);
}

WASI_P2_FN void wasi_io_streams_output_stream_flush(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_stream *st = wasi_p2_output_get(s, self);
    int status = st->flush(s, st);
    if (status != WASI_P2_STREAM_OK) {
        wasi_p2_stream_err(s, comp, retptr, retptr + 4, status, st);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
}

WASI_P2_FN void wasi_io_streams_output_stream_blocking_flush(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_io_streams_output_stream_flush(s, comp, self, retptr);
}

WASI_P2_FN void wasi_p2_splice(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t src, uint64_t len, uint32_t retptr, int block) {
    wasi_p2_stream *out = wasi_p2_output_get(s, self);
    wasi_p2_stream *in = wasi_p2_input_get(s, src);
    uint8_t *buf = NULL;
    uint64_t got = 0;
    int status = WASI_P2_STREAM_OK;
    wasi_p2_stream *failed = NULL; /* the stream that failed, for the error */
    for (;;) {
        uint64_t budget = out->check_write(s, out, &status);
        if (status != WASI_P2_STREAM_OK) {
            failed = out;
            break;
        }
        if (budget == 0 && block) {
            s->wait(s);
            continue;
        }
        if (budget) {
            status = wasi_p2_read(s, in, len < budget ? len : budget, block, &buf, &got);
            if (status != WASI_P2_STREAM_OK) {
                failed = in;
                break;
            }
            status = out->write(s, out, buf, got);
            if (status != WASI_P2_STREAM_OK) failed = out;
        }
        break;
    }
    free(buf);
    if (status != WASI_P2_STREAM_OK) {
        wasi_p2_stream_err(s, comp, retptr, retptr + 8, status, failed);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u64(s, comp, retptr + 8, got);
}

WASI_P2_FN void wasi_io_streams_output_stream_splice(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t src, uint64_t len, uint32_t retptr) {
    wasi_p2_splice(s, comp, self, src, len, retptr, 0);
}
WASI_P2_FN void wasi_io_streams_output_stream_blocking_splice(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t src, uint64_t len, uint32_t retptr) {
    wasi_p2_splice(s, comp, self, src, len, retptr, 1);
}

WASI_P2_FN uint32_t wasi_io_streams_output_stream_subscribe(wasi_p2_state *s, uint32_t self) {
    return wasi_p2_stream_pollable(s, wasi_p2_output_get(s, self));
}

WASI_P2_FN void wasi_io_streams_output_stream_drop(wasi_p2_state *s, uint32_t handle) {
    wasi_p2_output_get(s, handle);
    wasi_p2_table_drop(s, handle, WASI_P2_KIND_OUTPUT_STREAM);
}

#endif /* WASI_P2_IO_H */
