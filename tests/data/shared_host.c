/* A host in C for the shared library of tests/data/shared_module.wat: no Python anywhere. Prints one line for each thing it checks; the test reads them. */
#include <stdio.h>
#include <string.h>
#include "mod_api.h"

typedef struct { int calls; int fail_at; } log_state;

static int32_t host_log(void *user, int32_t a, int *trapped) {
    log_state *s = (log_state *)user;
    s->calls++;
    if (s->fail_at && s->calls == s->fail_at) {  /* a failure of the host function: nonzero through trapped, its own error kept here */
        *trapped = 1;
        return 0;
    }
    return a + 100;
}

int main(void) {
    int error = 0, rc;
    mod_store_t *m_s = mod_store_new(NULL, &error);
    mod_t *m = mod_new(m_s, &error);
    if (m == NULL) { printf("new failed %d\n", error); return 1; }
    int32_t r0 = 0, r1 = 0;
    rc = mod_instantiate(m);
    printf("instantiate without the import: %s\n", rc == MOD_LINK_ERROR ? "LINK_ERROR" : "other");
    log_state state = {0, 3};
    mod_set_import0(m, host_log, &state);
    rc = mod_instantiate(m);
    printf("instantiate: %d\n", rc);
    r0 = mod_add(m, 2, 3);
    rc = mod_status(m);
    printf("add: %d %d\n", rc, r0);
    rc = mod_twice(m, 7, &r0, &r1);
    printf("twice: %d %d %d\n", rc, r0, r1);
    r0 = mod_call_log(m, 1);
    rc = mod_status(m);
    printf("call_log: %d %d\n", rc, r0);
    r0 = mod_call_log(m, 2);
    rc = mod_status(m);
    printf("call_log again: %d %d\n", rc, r0);
    r0 = mod_call_log(m, 3);  /* the third call of the host function fails */
    rc = mod_status(m);
    printf("call_log failing: %s, host calls %d\n", rc == MOD_TRAP_HOST ? "TRAP_HOST" : "other", state.calls);
    r0 = mod_add(m, 40, 2);
    rc = mod_status(m);
    printf("add after the failure: %d %d\n", rc, r0);
    rc = mod_trap(m);
    printf("trap: %d (%s)\n", rc != 0, mod_trap_message(rc));
    rc = mod_boom(m, -9);
    int tag = -1;
    mod_value values[4];
    size_t count = 0;
    mod_exception(m, &tag, values, 4, &count);
    printf("boom: exception %d tag %d count %zu value %d\n", mod_trap_is_exception(rc), tag, count, count ? values[0].as.i32 : 0);
    size_t size = 0;
    uint8_t *memory = mod_memory_mem(m, &size);
    printf("memory: %zu %c%c\n", size, memory[0], memory[1]);
    mod_free(m);
    mod_store_free(m_s);
    return 0;
}
