/* The scenarios of tests/test_wasi_p2_http.py, in C: a fake memory, a server on the loopback (or the transport of the embedder below); the output is compared with the Python host's.
   Usage: driver <scenario> <port of the server> <a port where nothing listens> */
#include <inttypes.h>

#include "wasi_p2_http.h"

/* the arguments of `fetch` are given by position and the rest is zero */
#pragma GCC diagnostic ignored "-Wmissing-field-initializers"

static wasi_p2_state s;
static uint8_t memory[1 << 16];
static uint32_t next_free = 40000, next_input = 4000;
#define R 100

static void trap(wasi_p2_state *st, const char *m) {
    (void)st;
    printf("TRAP %s\n", m);
    exit(0);
}
static int allow_all(wasi_p2_state *st, const char *scheme, const char *authority) {
    (void)st, (void)scheme, (void)authority;
    return 1;
}
static int check_authority(wasi_p2_state *st, const char *scheme, const char *authority) {
    (void)st, (void)scheme;
    return strcmp(authority, "allowed.test:80") == 0;
}
static uint32_t bump(wasi_p2_state *st, uint32_t comp, uint32_t old_ptr, uint32_t old_size, uint32_t align, uint32_t new_size) {
    (void)st, (void)comp, (void)old_ptr, (void)old_size;
    uint32_t ptr = (next_free + align - 1) / align * align;
    next_free = ptr + new_size;
    return ptr;
}

static uint32_t u32(uint32_t off) { return wasi_p2_load_u32(&s, 0, off); }
static void clear(void) { memset(memory + R, 0, 64); }
static void hex(const uint8_t *p, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) printf("%02x", p[i]);
}
static uint32_t put(const void *data, uint32_t n) {
    uint32_t ptr = next_input;
    if (n) memcpy(memory + ptr, data, n);
    next_input = (ptr + n + 8) / 8 * 8;
    return ptr;
}
static uint32_t puts_(const char *t) { return put(t, (uint32_t)strlen(t)); }

struct kv {
    const char *k, *v;
};

static void error_at(const char *label, uint32_t off) {
    printf("%s error:", label);
    hex(memory + off, 32);
    printf("\n");
}

static uint32_t pairs(const struct kv *items) {
    uint32_t n = 0, spans[16][4];
    for (; items && items[n].k; n++) {
        spans[n][0] = puts_(items[n].k), spans[n][1] = (uint32_t)strlen(items[n].k);
        spans[n][2] = puts_(items[n].v), spans[n][3] = (uint32_t)strlen(items[n].v);
    }
    uint8_t zeros[16 * 16];
    memset(zeros, 0, sizeof zeros);
    uint32_t arr = put(zeros, 16 * n);
    for (uint32_t i = 0; i < n; i++)
        for (uint32_t k = 0; k < 4; k++) wasi_p2_store_u32(&s, 0, arr + 16 * i + 4 * k, spans[i][k]);
    return arr;
}
static uint32_t pairs_count(const struct kv *items) {
    uint32_t n = 0;
    while (items && items[n].k) n++;
    return n;
}

/* a list<list<u8>> */
static uint32_t blobs(const char *const *items, uint32_t n) {
    uint32_t spans[8][2];
    for (uint32_t i = 0; i < n; i++) spans[i][0] = puts_(items[i]), spans[i][1] = (uint32_t)strlen(items[i]);
    uint8_t zeros[64];
    memset(zeros, 0, sizeof zeros);
    uint32_t arr = put(zeros, 8 * n);
    for (uint32_t i = 0; i < n; i++) wasi_p2_store_u32(&s, 0, arr + 8 * i, spans[i][0]), wasi_p2_store_u32(&s, 0, arr + 8 * i + 4, spans[i][1]);
    return arr;
}

static uint32_t fields(const struct kv *items) {
    clear();
    wasi_http_types_fields_from_list(&s, 0, pairs(items), pairs_count(items), R);
    if (memory[R] != 0) printf("fields: unexpected error\n");
    return u32(R + 4);
}

static void show_entries(const char *label, uint32_t handle) {
    clear();
    wasi_http_types_fields_entries(&s, 0, handle, R);
    uint32_t ptr = u32(R), n = u32(R + 4);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t e = ptr + 16 * i;
        printf("  %s %.*s: %.*s\n", label, (int)u32(e + 4), (const char *)memory + u32(e), (int)u32(e + 12), (const char *)memory + u32(e + 8));
    }
}

static const char *const std_methods[9] = {"GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"};

static void method_args(const char *m, uint32_t out[3]) {
    for (uint32_t i = 0; i < 9; i++)
        if (strcmp(m, std_methods[i]) == 0) {
            out[0] = i, out[1] = out[2] = 0;
            return;
        }
    out[0] = 9, out[1] = puts_(m), out[2] = (uint32_t)strlen(m);
}
static void scheme_args(const char *sc, uint32_t out[4]) {
    if (!sc) {
        out[0] = out[1] = out[2] = out[3] = 0;
    } else if (!strcmp(sc, "http") || !strcmp(sc, "https")) {
        out[0] = 1, out[1] = !strcmp(sc, "https"), out[2] = out[3] = 0;
    } else {
        out[0] = 1, out[1] = 2, out[2] = puts_(sc), out[3] = (uint32_t)strlen(sc);
    }
}
static void opt_text(const char *t, uint32_t out[3]) {
    if (!t) out[0] = out[1] = out[2] = 0;
    else out[0] = 1, out[1] = puts_(t), out[2] = (uint32_t)strlen(t);
}

static uint32_t make_request(const char *method, const char *scheme, const char *authority, const char *path, const struct kv *headers) {
    uint32_t req = wasi_http_types_outgoing_request_new(&s, fields(headers));
    uint32_t a[4];
    method_args(method, a);
    printf("  set-method %u\n", wasi_http_types_outgoing_request_set_method(&s, 0, req, a[0], a[1], a[2]));
    scheme_args(scheme, a);
    printf("  set-scheme %u\n", wasi_http_types_outgoing_request_set_scheme(&s, 0, req, a[0], a[1], a[2], a[3]));
    opt_text(authority, a);
    printf("  set-authority %u\n", wasi_http_types_outgoing_request_set_authority(&s, 0, req, a[0], a[1], a[2]));
    opt_text(path, a);
    printf("  set-path %u\n", wasi_http_types_outgoing_request_set_path_with_query(&s, 0, req, a[0], a[1], a[2]));
    return req;
}

static void write_body(const char *body, const struct kv *trailers, uint32_t req, const char *label) {
    clear();
    wasi_http_types_outgoing_request_body(&s, 0, req, R);
    uint32_t body_h = u32(R + 4);
    if (body) {
        clear();
        wasi_http_types_outgoing_body_write(&s, 0, body_h, R);
        uint32_t stream = u32(R + 4);
        clear();
        wasi_io_streams_output_stream_blocking_write_and_flush(&s, 0, stream, puts_(body), (uint32_t)strlen(body), R);
        wasi_io_streams_output_stream_drop(&s, stream);
    }
    uint32_t t = trailers ? fields(trailers) : 0;
    clear();
    wasi_http_types_outgoing_body_finish(&s, 0, body_h, trailers != NULL, t, R);
    if (memory[R] == 1) {
        char text[128];
        snprintf(text, sizeof text, "%s finish", label);
        error_at(text, R + 8);
    }
}

/* reads a stream to its end; the bytes are printed as hex by the caller */
static uint32_t read_all(uint32_t stream, uint8_t *out, uint32_t cap) {
    uint32_t got = 0;
    for (;;) {
        clear();
        wasi_io_streams_input_stream_read(&s, 0, stream, 4096, R);
        if (memory[R] == 1) {
            if (memory[R + 4] == 0) printf("  body stream failed\n");
            return got;
        }
        uint32_t n = u32(R + 8);
        if (got + n <= cap) memcpy(out + got, memory + u32(R + 4), n);
        got += n;
    }
}

static uint32_t append_xy(uint32_t handle) {
    clear();
    wasi_http_types_fields_append(&s, 0, handle, puts_("x"), 1, puts_("y"), 1, R);
    return memory[R] * 100u + (memory[R] ? memory[R + 1] : 0u);
}

static void receive(const char *label, uint32_t fut) {
    static uint8_t data[1 << 16];
    uint32_t pol = wasi_http_types_future_incoming_response_subscribe(&s, fut);
    wasi_io_poll_pollable_block(&s, pol);
    wasi_io_poll_pollable_drop(&s, pol);
    clear();
    wasi_http_types_future_incoming_response_get(&s, 0, fut, R);
    printf("  get tags %u %u %u\n", memory[R], memory[R + 8], memory[R + 16]);
    if (memory[R + 16] == 1) {
        error_at(label, R + 24);
        return;
    }
    uint32_t resp = u32(R + 24);
    printf("  status %u\n", wasi_http_types_incoming_response_status(&s, resp));
    uint32_t headers = wasi_http_types_incoming_response_headers(&s, resp);
    show_entries("header", headers);
    printf("  append to the headers of an answer %u\n", append_xy(headers));
    wasi_http_types_fields_drop(&s, headers);
    clear();
    wasi_http_types_incoming_response_consume(&s, 0, resp, R);
    uint32_t body = u32(R + 4);
    clear();
    wasi_http_types_incoming_response_consume(&s, 0, resp, R);
    printf("  consume again %u\n", memory[R]);
    clear();
    wasi_http_types_incoming_body_stream(&s, 0, body, R);
    uint32_t stream = u32(R + 4);
    uint32_t n = read_all(stream, data, sizeof data);
    printf("  body ");
    hex(data, n);
    printf("\n");
    clear();
    wasi_http_types_incoming_body_stream(&s, 0, body, R);
    printf("  stream again %u\n", memory[R]);
    wasi_io_streams_input_stream_drop(&s, stream);
    uint32_t trailers = wasi_http_types_incoming_body_finish(&s, body);
    pol = wasi_http_types_future_trailers_subscribe(&s, trailers);
    wasi_io_poll_pollable_block(&s, pol);
    wasi_io_poll_pollable_drop(&s, pol);
    clear();
    wasi_http_types_future_trailers_get(&s, 0, trailers, R);
    printf("  trailers tags %u %u %u %u\n", memory[R], memory[R + 8], memory[R + 16], memory[R + 24]);
    if (memory[R + 24] == 1) show_entries("trailer", u32(R + 28));
    clear();
    wasi_http_types_future_trailers_get(&s, 0, trailers, R);
    printf("  trailers again %u %u\n", memory[R], memory[R + 8]);
    wasi_http_types_future_trailers_drop(&s, trailers);
    wasi_http_types_incoming_response_drop(&s, resp);
}

struct fetch {
    const char *label, *authority, *path, *method, *scheme;
    const struct kv *headers;
    const char *body;
    const struct kv *trailers;
    int has_first, has_connect;
    uint64_t first_ns, connect_ns;
};

static void fetch(struct fetch f) {
    if (!f.method) f.method = "GET";
    printf("== %s\n", f.label);
    uint32_t req = make_request(f.method, f.scheme, f.authority, f.path, f.headers);
    if (f.body || f.trailers) write_body(f.body, f.trailers, req, f.label);
    uint32_t opts = 0;
    if (f.has_first || f.has_connect) {
        opts = wasi_http_types_request_options_new(&s);
        if (f.has_first) wasi_http_types_request_options_set_first_byte_timeout(&s, opts, 1, f.first_ns);
        if (f.has_connect) wasi_http_types_request_options_set_connect_timeout(&s, opts, 1, f.connect_ns);
    }
    clear();
    wasi_http_outgoing_handler_handle(&s, 0, req, opts ? 1 : 0, opts, R);
    if (memory[R] == 1) {
        error_at(f.label, R + 8);
        return;
    }
    receive(f.label, u32(R + 8));
}

/* the transport of the embedder: the table of failures and the echo of the request (the same as in the test) */
static void set_fail(wasi_p2_http_error *e, int i) {
    switch (i) {
    case 0: wasi_p2_http_fail(e, WASI_P2_HTTP_DNS_TIMEOUT); break;
    case 1: wasi_p2_http_fail_str(e, WASI_P2_HTTP_DNS_ERROR, 0, "NXDOMAIN"); break;
    case 2: wasi_p2_http_fail_str(e, WASI_P2_HTTP_DNS_ERROR, 0, "rc"), wasi_p2_http_error_set_num(e, 1, 7); break;
    case 3: wasi_p2_http_fail(e, WASI_P2_HTTP_TLS_ALERT_RECEIVED), wasi_p2_http_error_set_num(e, 0, 42), wasi_p2_http_error_set_str(e, 1, "bad", 3); break;
    case 4: wasi_p2_http_fail(e, WASI_P2_HTTP_TLS_ALERT_RECEIVED); break;
    case 5: wasi_p2_http_fail_num(e, WASI_P2_HTTP_REQUEST_BODY_SIZE, (1ULL << 40) + 5); break;
    case 6: wasi_p2_http_fail(e, WASI_P2_HTTP_REQUEST_BODY_SIZE); break;
    case 7: wasi_p2_http_fail_str(e, WASI_P2_HTTP_REQUEST_HEADER_SIZE, 0, "name"), wasi_p2_http_error_set_num(e, 1, 99); break;
    case 8: wasi_p2_http_fail(e, WASI_P2_HTTP_REQUEST_HEADER_SIZE), e->present = 0; break;
    case 9: wasi_p2_http_fail_str(e, WASI_P2_HTTP_RESPONSE_HEADER_SIZE, 0, "h"); break;
    case 10: wasi_p2_http_fail_num(e, WASI_P2_HTTP_RESPONSE_HEADER_SECTION_SIZE, 65536); break;
    case 11: wasi_p2_http_fail_str(e, WASI_P2_HTTP_RESPONSE_TRANSFER_CODING, 0, "gzip"); break;
    case 12: wasi_p2_http_fail_str(e, WASI_P2_HTTP_INTERNAL_ERROR, 0, "oops"); break;
    case 13: wasi_p2_http_fail(e, WASI_P2_HTTP_INTERNAL_ERROR); break;
    case 14: wasi_p2_http_fail(e, WASI_P2_HTTP_CONNECTION_REFUSED); break;
    default: wasi_p2_http_fail(e, WASI_P2_HTTP_LOOP_DETECTED); break;
    }
}
#define FAILS 16

static void add_text(char **buf, size_t *len, size_t *cap, const char *t) { wasi_p2_http_append((uint8_t **)buf, len, cap, (const uint8_t *)t, strlen(t)); }

static int hook(wasi_p2_state *st, const wasi_p2_http_request *req, wasi_p2_http_response *out, wasi_p2_http_error *err) {
    (void)st;
    if (strncmp(req->path, "/fail/", 6) == 0) {
        set_fail(err, atoi(req->path + 6));
        return 1;
    }
    char *buf = NULL;
    size_t len = 0, cap = 0;
    add_text(&buf, &len, &cap, req->method), add_text(&buf, &len, &cap, " "), add_text(&buf, &len, &cap, req->scheme), add_text(&buf, &len, &cap, " ");
    add_text(&buf, &len, &cap, req->authority), add_text(&buf, &len, &cap, " "), add_text(&buf, &len, &cap, req->path);
    for (uint32_t i = 0; i < req->headers->count; i++) {
        add_text(&buf, &len, &cap, "\n"), add_text(&buf, &len, &cap, req->headers->e[i].name), add_text(&buf, &len, &cap, ": ");
        wasi_p2_http_append((uint8_t **)&buf, &len, &cap, req->headers->e[i].value, req->headers->e[i].len);
    }
    add_text(&buf, &len, &cap, "\nbody=");
    wasi_p2_http_append((uint8_t **)&buf, &len, &cap, req->body, (size_t)req->body_len);
    if (req->trailers) {
        for (uint32_t i = 0; i < req->trailers->count; i++) {
            add_text(&buf, &len, &cap, "\ntrailer "), add_text(&buf, &len, &cap, req->trailers->e[i].name), add_text(&buf, &len, &cap, ": ");
            wasi_p2_http_append((uint8_t **)&buf, &len, &cap, req->trailers->e[i].value, req->trailers->e[i].len);
        }
    }
    out->status = 201;
    out->headers = wasi_p2_http_fields_new(1);
    wasi_p2_http_fields_add(out->headers, "X-Upper", 7, "One", 3);
    wasi_p2_http_fields_add(out->headers, "x-dup", 5, "a", 1);
    wasi_p2_http_fields_add(out->headers, "X-DUP", 5, "b", 1);
    out->body = wasi_p2_http_blob_new(buf, len);
    out->trailers = wasi_p2_http_fields_new(1);
    wasi_p2_http_fields_add(out->trailers, "X-Trailer", 9, "t", 1);
    free(buf);
    return 0;
}

static void describe(const wasi_p2_http_error *e) {
    const wasi_p2_http_case *c = wasi_p2_http_case_of(e->tag);
    printf("%u/%d/", e->tag, e->present);
    for (int i = 0; i < c->leaves; i++) {
        if (i) printf("/");
        if (!e->has[i]) printf("-");
        else if (c->kind[i] == WASI_P2_HK_STR) printf("%s", e->str[i]);
        else printf("%" PRIu64, e->num[i]);
    }
}

static void get_values(uint32_t handle, const char *name) {
    clear();
    wasi_http_types_fields_get(&s, 0, handle, puts_(name), (uint32_t)strlen(name), R);
    uint32_t list = u32(R), n = u32(R + 4);
    printf("get %s: [", name);
    for (uint32_t i = 0; i < n; i++)
        printf("%s'%.*s'", i ? ", " : "", (int)u32(list + 8 * i + 4), (const char *)memory + u32(list + 8 * i));
    printf("]\n");
}

typedef void (*getter_fn)(wasi_p2_state *, uint32_t, uint32_t, uint32_t);

static void text_of(const char *label, getter_fn getter, uint32_t req) {
    clear();
    getter(&s, 0, req, R);
    printf("%s: ", label);
    hex(memory + R, 16);
    printf(" ");
    if (memory[R]) hex(memory + u32(R + 4), u32(R + 8));
    printf("\n");
}

static void scheme_of(uint32_t req) {
    clear();
    wasi_http_types_outgoing_request_scheme(&s, 0, req, R);
    printf("scheme: ");
    hex(memory + R, 16);
    printf("\n");
}

static void quoted(const char *t) {
    if (t) printf("'%s'", t);
    else printf("None");
}

#define TIMEOUT(which, WHICH)                                                                                                \
    do {                                                                                                                      \
        clear();                                                                                                              \
        wasi_http_types_request_options_##which##_timeout(&s, 0, opts, R);                                                    \
        printf("%s ", #which), hex(memory + R, 16), printf("\n");                                                            \
        printf("set %s %u\n", #which, wasi_http_types_request_options_set_##which##_timeout(&s, opts, 1, 123456789012ULL)); \
        clear();                                                                                                              \
        wasi_http_types_request_options_##which##_timeout(&s, 0, opts, R);                                                    \
        printf("%s ", #which), hex(memory + R, 16), printf("\n");                                                            \
        wasi_http_types_request_options_set_##which##_timeout(&s, opts, 0, 5);                                               \
        clear();                                                                                                              \
        wasi_http_types_request_options_##which##_timeout(&s, 0, opts, R);                                                    \
        printf("%s ", #which), hex(memory + R, 16), printf("\n");                                                            \
    } while (0)

int main(int argc, char **argv) {
    const char *scenario = argc > 1 ? argv[1] : "main";
    int port = argc > 2 ? atoi(argv[2]) : 0, dead = argc > 3 ? atoi(argv[3]) : 0;
    char me[64], nobody[64];
    snprintf(me, sizeof me, "127.0.0.1:%d", port);
    snprintf(nobody, sizeof nobody, "127.0.0.1:%d", dead);
    wasi_p2_init(&s);
    wasi_p2_set_memory(&s, 0, memory, sizeof memory);
    s.realloc = bump;
    s.trap = trap;
    int denied = !strcmp(scenario, "denied") || !strcmp(scenario, "check");
    s.http_check = !strcmp(scenario, "check") ? check_authority : denied ? NULL : allow_all;
    if (!strcmp(scenario, "hook") || !strcmp(scenario, "check") || !strcmp(scenario, "fields") || !strcmp(scenario, "setters") || !strcmp(scenario, "limits"))
        s.http_send = hook;

    if (!strcmp(scenario, "main")) {
        struct kv h1[] = {{"X-Test", "1"}, {NULL, NULL}}, h2[] = {{"Content-Type", "text/x"}, {NULL, NULL}}, t1[] = {{"X-End", "yes"}, {NULL, NULL}};
        fetch((struct fetch){"hello", me, "/hello", "GET", "http", h1});
        fetch((struct fetch){"echo", me, "/echo?a=b", "POST", "http", h2, "ping"});
        fetch((struct fetch){"echo with trailers", me, "/echo", "POST", "http", NULL, "data", t1});
        fetch((struct fetch){"head", me, "/hello", "HEAD", "http"});
        fetch((struct fetch){"chunked", me, "/chunked", "GET", "http"});
        fetch((struct fetch){"status 404", me, "/status/404", "GET", "http"});
        fetch((struct fetch){"informational first", me, "/info", "GET", "http"});
        fetch((struct fetch){"until close", me, "/closeend", "GET", "http"});
        fetch((struct fetch){"truncated", me, "/truncated", "GET", "http"});
        fetch((struct fetch){"silent server", me, "/slow", "GET", "http", .has_first = 1, .first_ns = 100000000});
        fetch((struct fetch){"bad status", me, "/badstatus", "GET", "http"});
        fetch((struct fetch){"transfer coding", me, "/te", "GET", "http"});
        fetch((struct fetch){"bad chunk", me, "/badchunk", "GET", "http"});
        fetch((struct fetch){"long head", me, "/bighead", "GET", "http"});
        fetch((struct fetch){"nothing listens", nobody, "/", "GET", "http"});
        fetch((struct fetch){"other method", me, "/echo", "PROPFIND", "http", NULL, "x"});
    } else if (denied) {
        fetch((struct fetch){"denied", me, "/hello", "GET", "http"});
        fetch((struct fetch){"allowed", "allowed.test:80", "/a", "GET", "http"});
    } else if (!strcmp(scenario, "hook")) {
        struct kv h[] = {{"X-A", "1"}, {"x-a", "2"}, {NULL, NULL}}, t[] = {{"T1", "v"}, {NULL, NULL}};
        fetch((struct fetch){"echo", "example.test", "/a?b=1", "POST", "http", h, "hi"});
        fetch((struct fetch){"with trailers", "example.test", "/t", "PUT", "http", NULL, "t", t});
        fetch((struct fetch){"no authority", NULL, "/a", "GET", "http"});
        fetch((struct fetch){"bad scheme", "example.test", "/a", "GET", "ftp"});
        fetch((struct fetch){"bad method", "example.test", "/a", "BAD METHOD", "http"});
        fetch((struct fetch){"uri", "bad host!", "/a", "GET", "http"});
        for (int i = 0; i < FAILS; i++) {
            char label[32], path[32];
            snprintf(label, sizeof label, "fail %d", i);
            snprintf(path, sizeof path, "/fail/%d", i);
            fetch((struct fetch){label, "example.test", path, "GET", "http"});
        }
    } else if (!strcmp(scenario, "fields")) {
        struct kv init[] = {{"A", "1"}, {"b", "2"}, {"a", "3"}, {NULL, NULL}};
        uint32_t f = fields(init);
        show_entries("entries", f);
        get_values(f, "a"), get_values(f, "B"), get_values(f, "none");
        {
            uint32_t ha = wasi_http_types_fields_has(&s, 0, f, puts_("A"), 1);
            uint32_t hc = wasi_http_types_fields_has(&s, 0, f, puts_("c"), 1);
            printf("has A %u has c %u\n", ha, hc);
        }
        clear();
        wasi_http_types_fields_append(&s, 0, f, puts_("c"), 1, puts_("4"), 1, R);
        printf("append "), hex(memory + R, 2), printf("\n");
        const char *xy[] = {"x", "y"};
        clear();
        wasi_http_types_fields_set(&s, 0, f, puts_("A"), 1, blobs(xy, 2), 2, R);
        printf("set "), hex(memory + R, 2), printf("\n");
        show_entries("after set", f);
        clear();
        wasi_http_types_fields_delete(&s, 0, f, puts_("b"), 1, R);
        printf("delete "), hex(memory + R, 2), printf("\n");
        clear();
        wasi_http_types_fields_set(&s, 0, f, puts_("c"), 1, 0, 0, R);
        printf("set to nothing "), hex(memory + R, 2), printf("\n");
        show_entries("after delete", f);
        static const struct {
            const char *label, *name, *value;
            uint32_t vlen;
        } bad[] = {{"bad name", "a b", "x", 1},          {"empty name", "", "x", 1},       {"newline in value", "x", "a\nb", 3},
                   {"nul in value", "x", "a\0b", 3},     {"forbidden", "Transfer-Encoding", "chunked", 7}, {"forbidden host", "HOST", "x", 1},
                   {"tab is fine", "x", "a\tb", 3}};
        for (size_t i = 0; i < sizeof bad / sizeof *bad; i++) {
            clear();
            wasi_http_types_fields_append(&s, 0, f, puts_(bad[i].name), (uint32_t)strlen(bad[i].name), put(bad[i].value, bad[i].vlen), bad[i].vlen, R);
            printf("%s ", bad[i].label), hex(memory + R, 2), printf("\n");
        }
        struct kv forb[] = {{"ok", "1"}, {"connection", "x"}, {NULL, NULL}}, syn[] = {{"o k", "1"}, {NULL, NULL}};
        clear();
        wasi_http_types_fields_from_list(&s, 0, pairs(forb), 2, R);
        printf("from-list forbidden "), hex(memory + R, 8), printf("\n");
        clear();
        wasi_http_types_fields_from_list(&s, 0, pairs(syn), 1, R);
        printf("from-list syntax "), hex(memory + R, 8), printf("\n");
        uint32_t c = wasi_http_types_fields_clone(&s, f);
        clear();
        wasi_http_types_fields_delete(&s, 0, c, puts_("A"), 1, R);
        show_entries("clone", c);
        show_entries("original", f);
        uint32_t req = wasi_http_types_outgoing_request_new(&s, f);
        uint32_t headers = wasi_http_types_outgoing_request_headers(&s, req);
        printf("append to the headers of a request %u\n", append_xy(headers));
        clear();
        wasi_http_types_fields_delete(&s, 0, headers, puts_("A"), 1, R);
        printf("delete from the headers of a request "), hex(memory + R, 2), printf("\n");
        clear();
        wasi_http_types_fields_set(&s, 0, headers, puts_("A"), 1, 0, 0, R);
        printf("set on them "), hex(memory + R, 2), printf("\n");
        show_entries("request headers", headers);
    } else if (!strcmp(scenario, "setters")) {
        uint32_t req = wasi_http_types_outgoing_request_new(&s, fields((struct kv[]){{NULL, NULL}}));
        uint32_t a[4];
        text_of("method", wasi_http_types_outgoing_request_method, req);
        const char *methods[] = {"POST", "PATCH", "get", "bad method", "", "PROPFIND"};
        for (int i = 0; i < 6; i++) {
            method_args(methods[i], a);
            printf("set-method "), quoted(methods[i]), printf(" %u\n", wasi_http_types_outgoing_request_set_method(&s, 0, req, a[0], a[1], a[2]));
            text_of("method", wasi_http_types_outgoing_request_method, req);
        }
        const char *schemes[] = {NULL, "http", "https", "x-y.z+1", "1x", "a b", ""};
        for (int i = 0; i < 7; i++) {
            scheme_args(schemes[i], a);
            printf("set-scheme "), quoted(schemes[i]);
            printf(" %u\n", wasi_http_types_outgoing_request_set_scheme(&s, 0, req, a[0], a[1], a[2], a[3]));
            scheme_of(req);
        }
        const char *paths[] = {"/a?b=c", "*", "a", "/a b", "/\x7f", "", NULL};
        for (int i = 0; i < 7; i++) {
            opt_text(paths[i], a);
            printf("set-path "), quoted(paths[i]);
            printf(" %u\n", wasi_http_types_outgoing_request_set_path_with_query(&s, 0, req, a[0], a[1], a[2]));
            text_of("path", wasi_http_types_outgoing_request_path_with_query, req);
        }
        const char *auths[] = {"a.test", "a.test:8080", "[::1]:80", "[::1]", "a:b:c", "a:", "[::1]:", "a:0", "a:65536", "a:99999999999", "a b", "u@h", ":80", "", NULL};
        for (int i = 0; i < 15; i++) {
            opt_text(auths[i], a);
            printf("set-authority "), quoted(auths[i]);
            printf(" %u\n", wasi_http_types_outgoing_request_set_authority(&s, 0, req, a[0], a[1], a[2]));
            text_of("authority", wasi_http_types_outgoing_request_authority, req);
        }
        clear();
        wasi_http_types_outgoing_request_body(&s, 0, req, R);
        uint32_t first = memory[R];
        clear();
        wasi_http_types_outgoing_request_body(&s, 0, req, R);
        printf("body once %u then %u\n", first, memory[R]);
        uint32_t opts = wasi_http_types_request_options_new(&s);
        TIMEOUT(connect, CONNECT);
        TIMEOUT(first_byte, FIRST);
        TIMEOUT(between_bytes, BETWEEN);
        uint32_t resp_h = wasi_http_types_outgoing_response_new(&s, fields((struct kv[]){{NULL, NULL}}));
        printf("status %u\n", wasi_http_types_outgoing_response_status_code(&s, resp_h));
        const uint32_t codes[] = {99, 100, 599, 600, 200};
        for (int i = 0; i < 5; i++) printf("set-status %u %u\n", codes[i], wasi_http_types_outgoing_response_set_status_code(&s, resp_h, codes[i]));
        printf("status %u\n", wasi_http_types_outgoing_response_status_code(&s, resp_h));
    } else if (!strcmp(scenario, "limits")) {
        struct kv five[] = {{"content-length", "5"}, {NULL, NULL}}, two[] = {{"content-length", "2"}, {NULL, NULL}}, nan[] = {{"content-length", "x"}, {NULL, NULL}};
        fetch((struct fetch){"short body", "example.test", "/x", "POST", "http", five, "ab"});
        fetch((struct fetch){"right length", "example.test", "/x", "POST", "http", two, "ab"});
        fetch((struct fetch){"not a number", "example.test", "/x", "POST", "http", nan, "ab"});
    } else if (!strcmp(scenario, "server")) {
        wasi_p2_http_fields *h = wasi_p2_http_fields_new(1), *t = wasi_p2_http_fields_new(1);
        wasi_p2_http_fields_add(h, "A", 1, "1", 1), wasi_p2_http_fields_add(h, "a", 1, "2", 1), wasi_p2_http_fields_add(t, "t", 1, "v", 1);
        uint32_t req = wasi_p2_http_incoming_request_new(&s, "PUT", "/x?y=1", "https", "svc.test", h, "payload", 7, t);
        wasi_p2_http_fields_unref(h), wasi_p2_http_fields_unref(t);
        clear();
        wasi_http_types_incoming_request_method(&s, 0, req, R);
        printf("method "), hex(memory + R, 4), printf("\n");
        clear();
        wasi_http_types_incoming_request_path_with_query(&s, 0, req, R);
        printf("path "), hex(memory + R, 16), printf("\n");
        clear();
        wasi_http_types_incoming_request_scheme(&s, 0, req, R);
        printf("scheme "), hex(memory + R, 16), printf("\n");
        clear();
        wasi_http_types_incoming_request_authority(&s, 0, req, R);
        printf("authority "), hex(memory + R, 16), printf("\n");
        uint32_t hh = wasi_http_types_incoming_request_headers(&s, req);
        show_entries("header", hh);
        printf("append to them %u\n", append_xy(hh));
        clear();
        wasi_http_types_incoming_request_consume(&s, 0, req, R);
        uint32_t body = u32(R + 4);
        clear();
        wasi_http_types_incoming_request_consume(&s, 0, req, R);
        printf("consume again %u\n", memory[R]);
        clear();
        wasi_http_types_incoming_body_stream(&s, 0, body, R);
        uint32_t stream = u32(R + 4);
        uint8_t data[64];
        uint32_t n = read_all(stream, data, sizeof data);
        printf("body "), hex(data, n), printf("\n");
        wasi_io_streams_input_stream_drop(&s, stream);
        uint32_t trailers = wasi_http_types_incoming_body_finish(&s, body);
        clear();
        wasi_http_types_future_trailers_get(&s, 0, trailers, R);
        show_entries("trailer", u32(R + 28));
        uint32_t param;
        wasi_p2_http_outparam *out = wasi_p2_http_outparam_new(&s, &param);
        uint32_t resp_h = wasi_http_types_outgoing_response_new(&s, fields((struct kv[]){{"Content-Type", "text/plain"}, {NULL, NULL}}));
        printf("set-status %u\n", wasi_http_types_outgoing_response_set_status_code(&s, resp_h, 418));
        clear();
        wasi_http_types_outgoing_response_body(&s, 0, resp_h, R);
        uint32_t body_h = u32(R + 4);
        clear();
        wasi_http_types_outgoing_response_body(&s, 0, resp_h, R);
        printf("body again %u\n", memory[R]);
        clear();
        wasi_http_types_outgoing_body_write(&s, 0, body_h, R);
        stream = u32(R + 4);
        clear();
        wasi_http_types_outgoing_body_write(&s, 0, body_h, R);
        printf("write again %u\n", memory[R]);
        clear();
        wasi_io_streams_output_stream_blocking_write_and_flush(&s, 0, stream, puts_("tea"), 3, R);
        wasi_io_streams_output_stream_drop(&s, stream);
        wasi_http_types_response_outparam_set(&s, 0, param, 0, resp_h, 0, 0, 0, 0, 0, 0);
        printf("before finish: done %d finished %d\n", out->done, out->response ? out->response->body->finished : -1);
        clear();
        wasi_http_types_outgoing_body_finish(&s, 0, body_h, 0, 0, R);
        wasi_p2_http_oresponse *r = out->response;
        printf("embedder sees status %u body ", r->status), hex(r->body->buf, (uint32_t)r->body->len);
        printf(" finished %d trailers %s\n", r->body->finished, r->body->trailers ? "fields" : "None");
        for (uint32_t i = 0; i < r->headers->count; i++) printf("  %s: %.*s\n", r->headers->e[i].name, (int)r->headers->e[i].len, r->headers->e[i].value);
        wasi_p2_http_outparam_release(out);
        uint32_t param2;
        wasi_p2_http_outparam *out2 = wasi_p2_http_outparam_new(&s, &param2);
        wasi_http_types_response_outparam_drop(&s, param2);
        printf("dropped without a response: "), describe(&out2->error), printf("\n");
        wasi_p2_http_outparam_release(out2);
    } else if (!strcmp(scenario, "flat_errors")) {
        uint64_t cases[][8] = {
            {6},
            {1, 1, puts_("ab"), 2, 1, 7},
            {1, 0, 0, 0, 0, 0},
            {14, 1, 42, 1, puts_("xyz"), 3},
            {17, 1, (1ULL << 40) + 5},
            {17, 0, 0},
            {22, 1, 1, puts_("nm"), 2, 1, 99},
            {22, 0},
            {22, 1, 0, 0, 0, 1, 5},
            {38, 1, puts_("oops"), 4},
            {38, 0, 0, 0},
            {31, 1, puts_("gzip"), 4},
        };
        for (size_t i = 0; i < sizeof cases / sizeof *cases; i++) {
            uint32_t param;
            wasi_p2_http_outparam *o = wasi_p2_http_outparam_new(&s, &param);
            uint64_t *c = cases[i];
            wasi_http_types_response_outparam_set(&s, 0, param, 1, c[0], c[1], c[2], c[3], c[4], c[5], c[6]);
            printf("%u: ", (unsigned)c[0]), describe(&o->error), printf("\n");
            clear();
            if (o->failed) {
                wasi_p2_http_store_error(&s, 0, R, &o->error);
                printf("  stored "), hex(memory + R, 32), printf("\n");
            }
            wasi_p2_http_outparam_release(o);
        }
    } else if (!strcmp(scenario, "finish_alive")) {
        uint32_t req = wasi_http_types_outgoing_request_new(&s, fields((struct kv[]){{NULL, NULL}}));
        clear();
        wasi_http_types_outgoing_request_body(&s, 0, req, R);
        uint32_t body_h = u32(R + 4);
        clear();
        wasi_http_types_outgoing_body_write(&s, 0, body_h, R);
        clear();
        wasi_http_types_outgoing_body_finish(&s, 0, body_h, 0, 0, R);
    } else if (!strcmp(scenario, "bad_handle")) {
        wasi_http_types_fields_entries(&s, 0, 4242, R);
    } else if (!strcmp(scenario, "cases")) {
        for (uint32_t i = 0; i < WASI_P2_HTTP_CASES; i++) {
            const wasi_p2_http_case *c = wasi_p2_http_case_of(i);
            printf("%u %d %d %d %d\n", i, c->outer, c->leaves, c->kind[0], c->kind[1]);
        }
    }
    wasi_p2_free(&s);
    return 0;
}
