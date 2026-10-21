// provider_impl.c
#include "gen_provider/provider.h"
#include <string.h>
#include <stdlib.h>

static char last[256];
static uint32_t ncalls;

uint32_t exports_demo_text_host_lookup(provider_string_t *key) {
    ncalls++;
    uint32_t h = 0;
    for (size_t i = 0; i < key->len; i++) h = h * 31 + key->ptr[i];
    provider_string_free(key);
    return h % 1000;
}
void exports_demo_text_host_log(provider_string_t *msg) {
    ncalls++;
    size_t n = msg->len < sizeof last - 1 ? msg->len : sizeof last - 1;
    memcpy(last, msg->ptr, n); last[n] = 0;
    provider_string_free(msg);
}
void exports_demo_text_inspect_last_log(provider_string_t *ret) { provider_string_dup(ret, last); }
uint32_t exports_demo_text_inspect_calls(void) { return ncalls; }
