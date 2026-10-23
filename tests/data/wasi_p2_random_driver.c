/* The scenario of tests/test_wasi_p2_random.py, in C: sources that count bytes (secure from 0, insecure from 128), a fake memory. */
#include <inttypes.h>
#include "wasi_p2_random.h"

static void trap(wasi_p2_state *s, const char *m) { (void)s; printf("TRAP %s\n", m); exit(0); }

typedef struct {
    uint8_t secure, insecure; /* the counters of the two sources */
    uint32_t next;            /* the allocator */
} counters;

static int counting(wasi_p2_state *s, uint8_t *buf, size_t n) {
    counters *c = (counters *)s->user;
    for (size_t i = 0; i < n; i++) buf[i] = c->secure++;
    return 0;
}
static int counting_insecure(wasi_p2_state *s, uint8_t *buf, size_t n) {
    counters *c = (counters *)s->user;
    for (size_t i = 0; i < n; i++) buf[i] = c->insecure++;
    return 0;
}
static int failing(wasi_p2_state *s, uint8_t *buf, size_t n) { (void)s, (void)buf, (void)n; return 1; }

static uint32_t bump(wasi_p2_state *s, uint32_t comp, uint32_t old_ptr, uint32_t old_size, uint32_t align, uint32_t new_size) {
    counters *c = (counters *)s->user;
    (void)comp, (void)old_ptr, (void)old_size;
    uint32_t ptr = (c->next + align - 1) / align * align;
    c->next = ptr + new_size;
    return ptr;
}

static uint8_t memory[128];

static void dump(const char *what) {
    printf("%s ", what);
    for (int i = 0; i < 128; i++) printf("%02x", memory[i]);
    printf("\n");
}

int main(int argc, char **argv) {
    const char *scenario = argc > 1 ? argv[1] : "main";
    counters state = {0, 128, 64};
    wasi_p2_state s;
    wasi_p2_init(&s);
    s.trap = trap;
    s.user = &state;
    s.realloc = bump;
    s.random_bytes = counting;
    s.insecure_random_bytes = counting_insecure;
    wasi_p2_set_memory(&s, 0, memory, sizeof memory);
    if (!strcmp(scenario, "main")) {
        wasi_random_random_get_random_bytes(&s, 0, 5, 0), dump("bytes");
        printf("u64 %" PRIu64 "\n", wasi_random_random_get_random_u64(&s));
        wasi_random_insecure_get_insecure_random_bytes(&s, 0, 3, 8), dump("insecure bytes");
        printf("insecure u64 %" PRIu64 "\n", wasi_random_insecure_get_insecure_random_u64(&s));
        wasi_random_insecure_seed_insecure_seed(&s, 0, 16), dump("seed");
        wasi_random_random_get_random_bytes(&s, 0, 0, 32), dump("empty");
    } else if (!strcmp(scenario, "too_many")) {
        wasi_random_random_get_random_bytes(&s, 0, (uint64_t)1 << 40, 0);
    } else if (!strcmp(scenario, "failing")) {
        s.random_bytes = failing;
        wasi_random_random_get_random_u64(&s);
    }
    wasi_p2_free(&s);
    return 0;
}
