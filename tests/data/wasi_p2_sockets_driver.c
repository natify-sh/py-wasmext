/* The scenario of tests/test_wasi_p2_sockets.py, in C: real sockets on the loopback, a fake memory; the output is compared with the Python host's.
   Ports are those the system gives, so they are never printed; what is printed is whether they match. */
#include <inttypes.h>
#include <time.h>

#include "wasi_p2_sockets.h"

static wasi_p2_state s;
static uint8_t memory[4096];
#define R 100

static void trap(wasi_p2_state *st, const char *m) { (void)st; printf("TRAP %s\n", m); exit(0); }
static int allow_all(wasi_p2_state *st, const char *ip, uint16_t port, int use) { (void)st, (void)ip, (void)port, (void)use; return 1; }
static uint32_t bump(wasi_p2_state *st, uint32_t comp, uint32_t old_ptr, uint32_t old_size, uint32_t align, uint32_t new_size) {
    uint32_t *next = (uint32_t *)st->user;
    (void)comp, (void)old_ptr, (void)old_size;
    uint32_t ptr = (*next + align - 1) / align * align;
    *next = ptr + new_size;
    return ptr;
}

static void show(const char *label, uint32_t off, uint32_t n) {
    printf("%s:", label);
    for (uint32_t i = 0; i < n; i++) printf("%02x", memory[off + i]);
    printf("\n");
}
static uint32_t u32(uint32_t off) { return wasi_p2_load_u32(&s, 0, off); }
static uint16_t u16(uint32_t off) { return wasi_p2_load_u16(&s, 0, off); }
static void clear(void) { memset(memory + R, 0, 64); }
static void nap(void) {
#ifdef _WIN32
    Sleep(1);
#else
    struct timespec ts = {0, 1000000};
    nanosleep(&ts, NULL);
#endif
}

/* the flat form of an address: tag and eleven numbers */
#define A4(port, a, b, c, d) 0, (port), (a), (b), (c), (d), 0, 0, 0, 0, 0, 0
#define A6LOOP(port) 1, (port), 0, 0, 0, 0, 0, 0, 0, 0, 1, 0

#define T(fn, ...) wasi_sockets_tcp_tcp_socket_##fn(&s, 0, __VA_ARGS__)
#define U(fn, ...) wasi_sockets_udp_udp_socket_##fn(&s, 0, __VA_ARGS__)

/* calls that are tried again while the answer is would-block (8) */
static void settle_connect(uint32_t h) {
    for (int i = 0; i < 3000; i++) {
        clear();
        T(finish_connect, h, R);
        if (!(memory[R] == 1 && memory[R + 4] == WASI_P2_N_WOULD_BLOCK)) return;
        nap();
    }
}
static void settle_accept(uint32_t h) {
    for (int i = 0; i < 3000; i++) {
        clear();
        T(accept, h, R);
        if (!(memory[R] == 1 && memory[R + 4] == WASI_P2_N_WOULD_BLOCK)) return;
        nap();
    }
}
/* read from a stream until some bytes or an error; the bytes at the list, printed as hex */
static void read_some(const char *label, uint32_t h) {
    for (int i = 0; i < 3000; i++) {
        clear();
        wasi_io_streams_input_stream_read(&s, 0, h, 100, R);
        if (memory[R] == 1 || u32(R + 8) > 0) break;
        nap();
    }
    printf("%s ", label);
    if (memory[R] == 0) {
        printf("data ");
        for (uint32_t i = 0; i < u32(R + 8); i++) printf("%02x", memory[u32(R + 4) + i]);
        printf("\n");
    } else {
        printf("stream-error tag %u\n", memory[R + 4]);
    }
}
static void put_dgram(uint32_t idx, const char *data, int has_remote, uint32_t port) {
    uint32_t base = 2200 + 44 * idx, dptr = 2000 + 16 * idx, n = (uint32_t)strlen(data);
    memcpy(memory + dptr, data, n);
    memset(memory + base, 0, 44);
    wasi_p2_store_u32(&s, 0, base, dptr);
    wasi_p2_store_u32(&s, 0, base + 4, n);
    wasi_p2_store_u8(&s, 0, base + 8, (uint8_t)has_remote);
    if (has_remote) { /* 127.0.0.1:port as the variant at +12 */
        wasi_p2_store_u8(&s, 0, base + 12, 0);
        wasi_p2_store_u16(&s, 0, base + 16, (uint16_t)port);
        memory[base + 18] = 127, memory[base + 21] = 1;
    }
}
static void receive_some(const char *label, uint32_t h, uint32_t expect_port, int tries) {
    for (int i = 0; i < tries; i++) {
        clear();
        wasi_sockets_udp_incoming_datagram_stream_receive(&s, 0, h, 10, R);
        if (memory[R] == 1 || u32(R + 8) > 0) break;
        nap();
    }
    printf("%s ", label);
    if (memory[R] == 1) {
        printf("error %u\n", memory[R + 4]);
        return;
    }
    uint32_t n = u32(R + 8), list = u32(R + 4);
    printf("%u datagrams", n);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t d = list + 40 * i;
        printf(" [");
        for (uint32_t k = 0; k < u32(d + 4); k++) printf("%02x", memory[u32(d) + k]);
        printf(" from tag %u port-match %d]", memory[d + 8], expect_port ? u16(d + 12) == expect_port : -1);
    }
    printf("\n");
}

int main(int argc, char **argv) {
    const char *scenario = argc > 1 ? argv[1] : "main";
    uint32_t next = 3000;
    wasi_p2_init(&s);
    s.trap = trap;
    s.user = &next;
    s.realloc = bump;
    if (strcmp(scenario, "denied")) {
        s.socket_addr_check = allow_all;
        s.allow_ip_name_lookup = 1;
    }
    wasi_p2_set_memory(&s, 0, memory, sizeof memory);
    uint32_t net = wasi_sockets_instance_network_instance_network(&s);
    printf("network %u\n", net);
    if (!strcmp(scenario, "main")) {
        /* TCP: states and errors */
        clear();
        wasi_sockets_tcp_create_socket_create_tcp_socket(&s, 0, 0, R), show("create tcp", R, 8);
        uint32_t srv = u32(R + 4);
        printf("family %u listening %u\n", wasi_sockets_tcp_tcp_socket_address_family(&s, srv), wasi_sockets_tcp_tcp_socket_is_listening(&s, srv));
        clear(), T(local_address, srv, R), show("local address before bind", R, 8);
        clear(), T(start_bind, srv, net, A6LOOP(0), R), show("bind v6 on a v4 socket", R, 2);
        clear(), T(start_bind, srv, net, A4(0, 224, 0, 0, 1), R), show("bind multicast", R, 2);
        clear(), T(start_bind, srv, net, A4(0, 127, 0, 0, 1), R), show("start-bind", R, 2);
        clear(), T(local_address, srv, R), show("local address while binding", R, 8);
        clear(), T(finish_bind, srv, R), show("finish-bind", R, 2);
        clear(), T(finish_bind, srv, R), show("finish-bind again", R, 2);
        clear(), T(start_bind, srv, net, A4(0, 127, 0, 0, 1), R), show("bind again", R, 2);
        clear(), T(start_listen, srv, R), show("start-listen", R, 2);
        clear(), T(finish_listen, srv, R), show("finish-listen", R, 2);
        clear(), T(finish_listen, srv, R), show("finish-listen again", R, 2);
        printf("listening %u\n", wasi_sockets_tcp_tcp_socket_is_listening(&s, srv));
        clear(), T(accept, srv, R), show("accept with nothing waiting", R, 8);
        clear(), T(local_address, srv, R), show("listener", R, 1), show("  tag", R + 4, 1), show("  ip", R + 10, 4);
        uint32_t port = u16(R + 8);
        /* options */
        clear(), T(set_listen_backlog_size, srv, 0, R), show("backlog 0", R, 2);
        clear(), T(set_listen_backlog_size, srv, 10, R), show("backlog 10", R, 2);
        clear(), T(set_keep_alive_enabled, srv, 1, R), show("keep-alive on", R, 2);
        clear(), T(keep_alive_enabled, srv, R), show("keep-alive?", R, 2);
        clear(), T(set_keep_alive_idle_time, srv, 0, R), show("idle 0", R, 2);
        clear(), T(set_keep_alive_idle_time, srv, 30000000000ULL, R), show("idle 30 s", R, 2);
        clear(), T(keep_alive_idle_time, srv, R), show("idle?", R, 16);
        clear(), T(set_keep_alive_interval, srv, 5000000000ULL, R), T(keep_alive_interval, srv, R + 24), show("interval", R, 2), show("  value", R + 24, 16);
        clear(), T(set_keep_alive_count, srv, 3, R), T(keep_alive_count, srv, R + 24), show("count", R, 2), show("  value", R + 24, 8);
        clear(), T(set_hop_limit, srv, 0, R), show("hop-limit 0", R, 2);
        clear(), T(set_hop_limit, srv, 64, R), T(hop_limit, srv, R + 24), show("hop-limit 64", R, 2), show("  value", R + 24, 2);
        clear(), T(set_receive_buffer_size, srv, 0, R), show("receive buffer 0", R, 2);
        clear(), T(set_receive_buffer_size, srv, 65536, R), T(receive_buffer_size, srv, R + 24), show("receive buffer", R, 2);
        printf("  receive buffer > 0: %d\n", u32(R + 32) > 0);
        clear(), T(set_send_buffer_size, srv, 65536, R), T(send_buffer_size, srv, R + 24), show("send buffer", R, 2);
        printf("  send buffer > 0: %d\n", u32(R + 32) > 0);
        uint32_t listener_poll = wasi_sockets_tcp_tcp_socket_subscribe(&s, srv);
        printf("listener pollable %u ready %u\n", listener_poll, wasi_io_poll_pollable_ready(&s, listener_poll));
        /* connect and accept */
        clear(), wasi_sockets_tcp_create_socket_create_tcp_socket(&s, 0, 0, R);
        uint32_t cli = u32(R + 4);
        clear(), T(remote_address, cli, R), show("remote address before connect", R, 8);
        clear(), T(start_connect, cli, net, A4(0, 0, 0, 0, 0), R), show("connect to 0.0.0.0", R, 2);
        clear(), T(start_connect, cli, net, A4(80, 224, 0, 0, 1), R), show("connect to multicast", R, 2);
        clear(), T(start_connect, cli, net, A6LOOP(80), R), show("connect v6 on a v4 socket", R, 2);
        clear(), T(start_connect, cli, net, A4(port, 127, 0, 0, 1), R), show("start-connect", R, 2);
        clear(), T(start_connect, cli, net, A4(port, 127, 0, 0, 1), R), show("connect twice", R, 2);
        settle_connect(cli);
        show("finish-connect", R, 12);
        uint32_t cin = u32(R + 4), cout = u32(R + 8);
        clear(), T(finish_connect, cli, R), show("finish-connect again", R, 8);
        clear(), T(remote_address, cli, R), show("client remote", R, 1), printf("  remote port is the listener's: %d\n", u16(R + 8) == port);
        printf("listener pollable ready with a connection waiting %u\n", wasi_io_poll_pollable_ready(&s, listener_poll));
        settle_accept(srv);
        show("accept", R, 16);
        uint32_t conn = u32(R + 4), sin = u32(R + 8), sout = u32(R + 12);
        printf("listener pollable ready %u\n", wasi_io_poll_pollable_ready(&s, listener_poll));
        /* data both ways */
        memcpy(memory + 2000, "ping", 4);
        clear(), wasi_io_streams_output_stream_blocking_write_and_flush(&s, 0, cout, 2000, 4, R), show("client writes", R, 8);
        read_some("server reads", sin);
        memcpy(memory + 2000, "pong!", 5);
        clear(), wasi_io_streams_output_stream_blocking_write_and_flush(&s, 0, sout, 2000, 5, R), show("server writes", R, 8);
        read_some("client reads", cin);
        clear(), T(shutdown, cli, 1, R), show("client shutdown send", R, 2);
        read_some("server reads after the shutdown", sin);
        clear(), T(shutdown, cli, 1, R), show("shutdown again", R, 2);
        clear(), wasi_io_streams_output_stream_check_write(&s, 0, cout, R), show("client can write?", R, 8);
        clear(), T(shutdown, srv, 2, R), show("shutdown of a listener", R, 2);
        /* connection refused: the port of a listener that is gone */
        wasi_sockets_tcp_tcp_socket_drop(&s, srv);
        wasi_sockets_tcp_tcp_socket_drop(&s, conn);
        wasi_sockets_tcp_tcp_socket_drop(&s, cli);
        clear(), wasi_sockets_tcp_create_socket_create_tcp_socket(&s, 0, 0, R);
        uint32_t cli2 = u32(R + 4);
        clear(), T(start_connect, cli2, net, A4(port, 127, 0, 0, 1), R), show("connect to a closed port", R, 2);
        if (memory[R] == 0) settle_connect(cli2);
        show("  finished", R, 8);
        clear(), T(finish_connect, cli2, R), show("  and again", R, 8);
        wasi_sockets_tcp_tcp_socket_drop(&s, cli2);
        /* UDP */
        clear(), wasi_sockets_udp_create_socket_create_udp_socket(&s, 0, 0, R);
        uint32_t ua = u32(R + 4);
        clear(), wasi_sockets_udp_create_socket_create_udp_socket(&s, 0, 0, R);
        uint32_t ub = u32(R + 4);
        clear(), wasi_sockets_udp_create_socket_create_udp_socket(&s, 0, 0, R);
        uint32_t uc = u32(R + 4);
        clear(), U(stream, ua, 0, A4(0, 0, 0, 0, 0), R), show("udp stream before bind", R, 8);
        uint32_t sockets[3] = {ua, ub, uc}, ports[3];
        for (int i = 0; i < 3; i++) {
            clear(), U(start_bind, sockets[i], net, A4(0, 127, 0, 0, 1), R);
            clear(), U(finish_bind, sockets[i], R);
            clear(), U(local_address, sockets[i], R);
            ports[i] = u16(R + 8);
        }
        clear(), U(start_bind, ua, net, A4(0, 127, 0, 0, 1), R), show("udp bind again", R, 2);
        clear(), U(finish_bind, ua, R), show("udp finish-bind again", R, 2);
        clear(), U(stream, ua, 0, A4(0, 0, 0, 0, 0), R), show("stream a", R, 12);
        uint32_t ain = u32(R + 4), aout = u32(R + 8);
        clear(), U(stream, ub, 1, A4(ports[0], 127, 0, 0, 1), R), show("stream b to a", R, 12);
        uint32_t bin = u32(R + 4), bout = u32(R + 8);
        clear(), U(stream, uc, 0, A4(0, 0, 0, 0, 0), R);
        uint32_t cout_u = u32(R + 8);
        clear(), U(remote_address, ub, R), show("b remote", R, 1), printf("  is a: %d\n", u16(R + 8) == ports[0]);
        clear(), U(remote_address, ua, R), show("a remote", R, 8);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_check_send(&s, 0, bout, R), show("check-send", R, 16);
        put_dgram(0, "hello", 0, 0);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_send(&s, 0, bout, 2200, 1, R), show("b sends to its peer", R, 16);
        receive_some("a receives", ain, ports[1], 3000);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_check_send(&s, 0, aout, R);
        put_dgram(0, "back", 1, ports[1]);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_send(&s, 0, aout, 2200, 1, R), show("a sends to b", R, 16);
        receive_some("b receives", bin, ports[0], 3000);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_check_send(&s, 0, bout, R);
        put_dgram(0, "x", 1, ports[0]);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_send(&s, 0, bout, 2200, 1, R), show("b names its peer", R, 16);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_check_send(&s, 0, bout, R);
        put_dgram(0, "x", 1, ports[1]);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_send(&s, 0, bout, 2200, 1, R), show("b names another peer", R, 16);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_check_send(&s, 0, aout, R);
        put_dgram(0, "x", 0, 0);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_send(&s, 0, aout, 2200, 1, R), show("a names no peer", R, 16);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_check_send(&s, 0, cout_u, R);
        put_dgram(0, "stranger", 1, ports[1]);
        clear(), wasi_sockets_udp_outgoing_datagram_stream_send(&s, 0, cout_u, 2200, 1, R), show("c sends to b", R, 16);
        for (int i = 0; i < 20; i++) nap();
        receive_some("b receives from a stranger", bin, 0, 3);
        clear(), U(set_unicast_hop_limit, ua, 0, R), show("udp hop-limit 0", R, 2);
        clear(), U(set_unicast_hop_limit, ua, 7, R), U(unicast_hop_limit, ua, R + 24), show("udp hop-limit 7", R, 2), show("  value", R + 24, 2);
        clear(), U(set_send_buffer_size, ua, 0, R), show("udp send buffer 0", R, 2);
        wasi_sockets_udp_incoming_datagram_stream_drop(&s, ain);
        wasi_sockets_udp_outgoing_datagram_stream_drop(&s, aout);
        wasi_sockets_udp_udp_socket_drop(&s, ua);
        clear(), U(local_address, ub, R), show("b still bound", R, 1);
        /* names */
        static const char *names[] = {"127.0.0.1", "::1", "", "bad name!", "localhost", "a%b"};
        for (int i = 0; i < 6; i++) {
            uint32_t n = (uint32_t)strlen(names[i]);
            memcpy(memory + 2000, names[i], n);
            clear(), wasi_sockets_ip_name_lookup_resolve_addresses(&s, 0, net, 2000, n, R);
            printf("resolve [%s] ", names[i]);
            show("", R, 8);
            if (memory[R] == 0) {
                uint32_t rs = u32(R + 4);
                printf("  stream pollable ready %u\n", wasi_io_poll_pollable_ready(&s, wasi_sockets_ip_name_lookup_resolve_address_stream_subscribe(&s, rs)));
                for (int k = 0; k < 8; k++) {
                    clear(), wasi_sockets_ip_name_lookup_resolve_address_stream_resolve_next_address(&s, 0, rs, R);
                    if (!memory[R + 2]) {
                        printf("  end after %d\n", k);
                        break;
                    }
                    show("  address", R + 4, memory[R + 4] == 0 ? 6 : 18);
                }
                wasi_sockets_ip_name_lookup_resolve_address_stream_drop(&s, rs);
            }
        }
        /* an error that is not a network one */
        uint32_t e = wasi_p2_error_new(&s, "plain");
        clear(), wasi_sockets_network_network_error_code(&s, 0, e, R), show("network-error-code of a plain error", R, 2);
        wasi_sockets_network_network_drop(&s, net);
    } else if (!strcmp(scenario, "reset")) {
        /* a connection that the peer resets: the read fails with a network error-code, and then the stream is closed */
        clear(), wasi_sockets_tcp_create_socket_create_tcp_socket(&s, 0, 0, R);
        uint32_t srv = u32(R + 4);
        clear(), T(start_bind, srv, net, A4(0, 127, 0, 0, 1), R);
        clear(), T(finish_bind, srv, R);
        clear(), T(start_listen, srv, R);
        clear(), T(finish_listen, srv, R);
        clear(), T(local_address, srv, R);
        uint32_t port = u16(R + 8);
        clear(), wasi_sockets_tcp_create_socket_create_tcp_socket(&s, 0, 0, R);
        uint32_t cli = u32(R + 4);
        clear(), T(start_connect, cli, net, A4(port, 127, 0, 0, 1), R);
        settle_connect(cli);
        uint32_t cin = u32(R + 4);
        settle_accept(srv);
        uint32_t conn = u32(R + 4);
        struct linger lg = {1, 0};
        setsockopt(wasi_p2_tcp_get(&s, conn)->fd, SOL_SOCKET, SO_LINGER, (const char *)&lg, sizeof lg);
        wasi_sockets_tcp_tcp_socket_drop(&s, conn); /* closing with linger 0 sends a reset */
        read_some("read after a reset", cin);
        uint32_t err = u32(R + 8);
        clear(), wasi_sockets_network_network_error_code(&s, 0, err, R), show("network-error-code", R, 2);
        clear(), wasi_io_error_error_to_debug_string(&s, 0, err, R), printf("debug string is not empty: %d\n", u32(R + 4) > 0);
        read_some("and again", cin);
    } else if (!strcmp(scenario, "denied")) {
        clear(), wasi_sockets_tcp_create_socket_create_tcp_socket(&s, 0, 0, R);
        uint32_t t = u32(R + 4);
        clear(), T(start_bind, t, net, A4(0, 127, 0, 0, 1), R), show("tcp bind", R, 2);
        clear(), T(start_connect, t, net, A4(80, 127, 0, 0, 1), R), show("tcp connect", R, 2);
        clear(), wasi_sockets_udp_create_socket_create_udp_socket(&s, 0, 0, R);
        uint32_t u = u32(R + 4);
        clear(), U(start_bind, u, net, A4(0, 127, 0, 0, 1), R), show("udp bind", R, 2);
        memcpy(memory + 2000, "127.0.0.1", 9);
        clear(), wasi_sockets_ip_name_lookup_resolve_addresses(&s, 0, net, 2000, 9, R), show("resolve", R, 8);
    } else if (!strcmp(scenario, "udp_trap")) {
        clear(), wasi_sockets_udp_create_socket_create_udp_socket(&s, 0, 0, R);
        uint32_t u = u32(R + 4);
        clear(), U(start_bind, u, net, A4(0, 127, 0, 0, 1), R);
        clear(), U(finish_bind, u, R);
        clear(), U(stream, u, 0, A4(0, 0, 0, 0, 0), R);
        uint32_t out = u32(R + 8);
        put_dgram(0, "x", 1, 9);
        wasi_sockets_udp_outgoing_datagram_stream_send(&s, 0, out, 2200, 1, R);
    } else if (!strcmp(scenario, "bad_handle")) {
        wasi_sockets_tcp_tcp_socket_is_listening(&s, 4242);
    }
    wasi_p2_free(&s);
    return 0;
}
