/* The scenario of tests/test_wasi_p2_io.py, in C: a fake memory, a bump allocator for cabi_realloc, the output is compared with the one of the Python host. */
#include <inttypes.h>
#include "wasi_p2_io.h"

static void trap(wasi_p2_state *s, const char *m) { (void)s; printf("TRAP %s\n", m); exit(0); }

static uint32_t bump(wasi_p2_state *s, uint32_t comp, uint32_t old_ptr, uint32_t old_size, uint32_t align, uint32_t new_size) {
    uint32_t *next = (uint32_t *)s->user;
    (void)comp, (void)old_ptr, (void)old_size;
    uint32_t ptr = (*next + align - 1) / align * align;
    *next = ptr + new_size;
    return ptr;
}

static uint8_t memory[256];

static void dump(const char *what) {
    printf("%s ", what);
    for (int i = 0; i < 256; i++) printf("%02x", memory[i]);
    printf("\n");
}

static void hex(const char *what, const uint8_t *p, uint64_t n) {
    printf("%s ", what);
    for (uint64_t i = 0; i < n; i++) printf("%02x", p[i]);
    printf("\n");
}

int main(int argc, char **argv) {
    const char *scenario = argc > 1 ? argv[1] : "streams";
    uint32_t next = 160;
    wasi_p2_state s;
    wasi_p2_init(&s);
    s.trap = trap;
    s.user = &next;
    s.realloc = strcmp(scenario, "no_realloc") ? bump : NULL;
    wasi_p2_set_memory(&s, 0, memory, sizeof memory);
    memcpy(memory + 100, "hello", 5);
    static const uint8_t abc[] = "abcdefghij", xyz[] = "xyz";
    uint32_t i = wasi_p2_memory_input_new(&s, abc, 10), j = wasi_p2_memory_input_new(&s, xyz, 3), o, o2;
    wasi_p2_buffer_output *bo = wasi_p2_buffer_output_new(&s, 8, &o);
    wasi_p2_buffer_output *bo2 = wasi_p2_buffer_output_new(&s, 100, &o2);
    printf("handles %u %u %u %u\n", i, j, o, o2);
    if (!strcmp(scenario, "streams")) {
        wasi_io_streams_input_stream_read(&s, 0, i, 4, 0), dump("read");
        wasi_io_streams_input_stream_skip(&s, 0, i, 2, 16), dump("skip");
        wasi_io_streams_output_stream_check_write(&s, 0, o, 32), dump("check_write");
        wasi_io_streams_output_stream_write(&s, 0, o, 100, 5, 48), dump("write");
        wasi_io_streams_output_stream_check_write(&s, 0, o, 64), dump("check_write");
        wasi_io_streams_output_stream_write_zeroes(&s, 0, o, 3, 80), dump("write_zeroes");
        wasi_io_streams_output_stream_check_write(&s, 0, o, 96), dump("check_write");
        wasi_io_streams_output_stream_flush(&s, 0, o, 112), dump("flush");
        wasi_io_streams_output_stream_splice(&s, 0, o2, j, 10, 120), dump("splice");
        wasi_io_streams_output_stream_splice(&s, 0, o2, j, 10, 136), dump("splice");
        wasi_io_streams_input_stream_read(&s, 0, i, 100, 0), dump("read");
        wasi_io_streams_input_stream_read(&s, 0, i, 100, 16), dump("read");
        uint32_t p = wasi_io_streams_input_stream_subscribe(&s, i);
        printf("pollable %u ready %u\n", p, wasi_io_poll_pollable_ready(&s, p));
        wasi_p2_store_u32(&s, 0, 90, p);
        wasi_io_poll_poll(&s, 0, 90, 1, 32), dump("poll");
        wasi_io_poll_pollable_block(&s, p);
        uint32_t e = wasi_p2_error_new(&s, "boom");
        wasi_io_error_error_to_debug_string(&s, 0, e, 48), dump("to_debug_string");
        wasi_io_error_error_drop(&s, e);
        wasi_io_streams_output_stream_blocking_write_and_flush(&s, 0, o2, 100, 5, 64), dump("blocking_write_and_flush");
        wasi_io_streams_output_stream_blocking_write_zeroes_and_flush(&s, 0, o2, 50, 64), dump("blocking_write_zeroes_and_flush");
        wasi_io_streams_input_stream_blocking_read(&s, 0, j, 5, 16), dump("blocking_read");
        hex("o", bo->buf, bo->len);
        printf("o2 %" PRIu64 "\n", bo2->len);
        hex("o2", bo2->buf, 16);
        wasi_io_poll_pollable_drop(&s, p);
        wasi_io_streams_input_stream_drop(&s, i);
        wasi_io_streams_output_stream_drop(&s, o);
    } else if (!strcmp(scenario, "bad_handle")) {
        wasi_io_streams_input_stream_read(&s, 0, o, 4, 0);
    } else if (!strcmp(scenario, "oversize")) {
        wasi_io_streams_output_stream_write(&s, 0, o, 100, 5, 0); /* 5 fits in 8 */
        wasi_io_streams_output_stream_write(&s, 0, o, 100, 5, 0);             /* 3 are left: traps */
    } else if (!strcmp(scenario, "empty_poll")) {
        wasi_io_poll_poll(&s, 0, 90, 0, 32);
    } else if (!strcmp(scenario, "no_realloc")) {
        wasi_io_streams_input_stream_read(&s, 0, i, 4, 0);
    }
    wasi_p2_free(&s); /* the state first: it looks at the streams that are still alive */
    wasi_p2_buffer_output_release(bo);
    wasi_p2_buffer_output_release(bo2);
    return 0;
}
