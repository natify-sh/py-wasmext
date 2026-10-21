// guest_impl.c
#include "gen_guest/guest.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

void exports_demo_text_api_greet(guest_string_t *name, guest_string_t *ret) {
    char buf[256];
    guest_string_t msg;
    int n = snprintf(buf, sizeof buf, "greet(%.*s)", (int)name->len, (char *)name->ptr);
    guest_string_set(&msg, buf); (void)n;
    demo_text_host_log(&msg);                       /* host import: string in */
    uint32_t v = demo_text_host_lookup(name);       /* host import: string in, u32 out */
    snprintf(buf, sizeof buf, "hello, %.*s #%u", (int)name->len, (char *)name->ptr, v);
    guest_string_dup(ret, buf);
    guest_string_free(name);                        /* the argument is owned by the export */
}
