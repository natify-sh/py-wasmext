/* The scenario of tests/test_wasi_p2_clocks.py, in C: fixed clocks, a fake memory, the output is compared with the one of the Python host. */
#include <inttypes.h>
#include "wasi_p2_clocks.h"

static uint64_t wall(wasi_p2_state *s) { (void)s; return 1700000000123456789ULL; }
static uint64_t mono(wasi_p2_state *s) { (void)s; return 5000; }
static void trap(wasi_p2_state *s, const char *m) { (void)s; printf("TRAP %s\n", m); exit(0); }

static void dump(const uint8_t *m, int n) {
    for (int i = 0; i < n; i++) printf("%02x", m[i]);
    printf("\n");
}

int main(int argc, char **argv) {
    const char *scenario = argc > 1 ? argv[1] : "main";
    uint8_t memory[64] = {0};
    wasi_p2_state s;
    wasi_p2_init(&s);
    s.trap = trap;
    s.wall_ns = wall;
    s.monotonic_ns = mono;
    s.wall_resolution_ns = 1000;
    s.monotonic_resolution_ns = 7;
    wasi_p2_set_memory(&s, 0, memory, sizeof memory);
    if (!strcmp(scenario, "main")) {
        wasi_clocks_wall_clock_now(&s, 0, 0);
        wasi_clocks_wall_clock_resolution(&s, 0, 16);
        dump(memory, 32);
        printf("%" PRIu64 " %" PRIu64 "\n", wasi_clocks_monotonic_clock_now(&s), wasi_clocks_monotonic_clock_resolution(&s));
        uint32_t a = wasi_clocks_monotonic_clock_subscribe_duration(&s, 100);
        uint32_t b = wasi_clocks_monotonic_clock_subscribe_instant(&s, 9000);
        uint32_t c = wasi_clocks_monotonic_clock_subscribe_duration(&s, UINT64_MAX);
        printf("%u %u %u\n", a, b, c);
        printf("%" PRIu64 " %" PRIu64 " %" PRIu64 "\n", wasi_p2_table_get(&s, a, WASI_P2_KIND_POLLABLE)->value,
               wasi_p2_table_get(&s, b, WASI_P2_KIND_POLLABLE)->value, wasi_p2_table_get(&s, c, WASI_P2_KIND_POLLABLE)->value);
        wasi_p2_table_drop(&s, a, WASI_P2_KIND_POLLABLE);
        printf("%u\n", wasi_clocks_monotonic_clock_subscribe_instant(&s, 1)); /* the slot of `a` again, another generation */
    } else if (!strcmp(scenario, "double_drop")) {
        uint32_t a = wasi_clocks_monotonic_clock_subscribe_instant(&s, 1);
        wasi_p2_table_drop(&s, a, WASI_P2_KIND_POLLABLE);
        wasi_p2_table_drop(&s, a, WASI_P2_KIND_POLLABLE);
    } else if (!strcmp(scenario, "outside")) {
        wasi_clocks_wall_clock_now(&s, 0, 60); /* 16 bytes do not fit at 60 of 64 */
    } else if (!strcmp(scenario, "no_memory")) {
        wasi_clocks_wall_clock_now(&s, 1, 0);
    }
    wasi_p2_free(&s);
    return 0;
}
