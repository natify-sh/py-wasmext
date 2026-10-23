/* wasi:sockets (58 imports): network, instance-network, ip-name-lookup, tcp, tcp-create-socket, udp, udp-create-socket (the twin of p2/wasi_p2_sockets.py, where the
 * rules, the states and the layouts are described). BSD sockets, or Winsock on Windows (link ws2_32). Nothing is allowed unless `s->socket_addr_check` / `s->allow_ip_name_lookup` say so.
 * A socket is shared by its streams and its handle (a count of references), so a stream can outlive the handle of the socket; the descriptor is closed with the handle. */
#ifndef WASI_P2_SOCKETS_H
#define WASI_P2_SOCKETS_H

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <errno.h>
#ifdef _MSC_VER
#pragma comment(lib, "ws2_32") /* elsewhere: -lws2_32 */
typedef intptr_t ssize_t;
#endif
#else
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

#include "wasi_p2_io.h"

/* wasi:sockets/network error-code, in the order of the WIT */
enum {
    WASI_P2_N_UNKNOWN, WASI_P2_N_ACCESS_DENIED, WASI_P2_N_NOT_SUPPORTED, WASI_P2_N_INVALID_ARGUMENT, WASI_P2_N_OUT_OF_MEMORY, WASI_P2_N_TIMEOUT,
    WASI_P2_N_CONCURRENCY_CONFLICT, WASI_P2_N_NOT_IN_PROGRESS, WASI_P2_N_WOULD_BLOCK, WASI_P2_N_INVALID_STATE, WASI_P2_N_NEW_SOCKET_LIMIT,
    WASI_P2_N_ADDRESS_NOT_BINDABLE, WASI_P2_N_ADDRESS_IN_USE, WASI_P2_N_REMOTE_UNREACHABLE, WASI_P2_N_CONNECTION_REFUSED, WASI_P2_N_CONNECTION_RESET,
    WASI_P2_N_CONNECTION_ABORTED, WASI_P2_N_DATAGRAM_TOO_LARGE, WASI_P2_N_NAME_UNRESOLVABLE, WASI_P2_N_TEMPORARY_RESOLVER_FAILURE,
    WASI_P2_N_PERMANENT_RESOLVER_FAILURE
};
#define WASI_P2_NOK (-1) /* what the functions of this file return when nothing failed; a network error-code otherwise */

enum { WASI_P2_SS_UNBOUND, WASI_P2_SS_BIND_IN_PROGRESS, WASI_P2_SS_BOUND, WASI_P2_SS_LISTEN_IN_PROGRESS, WASI_P2_SS_LISTENING,
       WASI_P2_SS_CONNECT_IN_PROGRESS, WASI_P2_SS_CONNECTED, WASI_P2_SS_CLOSED };

#define WASI_P2_SOCK_CHUNK 65536u
#define WASI_P2_CHECK_SEND_PERMIT 16u
#define WASI_P2_BACKLOG_MAX 4096u


/* The system calls, as they are on POSIX and on Windows (Winsock): the descriptor is an `int` in this file (a SOCKET is a handle, whose value fits in 32 bits), the errors are
   those of `errno` (on Windows the WSA numbers are turned into them by `wasi_p2_errno`), and a socket is non-blocking. */
#ifdef _WIN32
#define WASI_P2_CLOSE(fd) closesocket((SOCKET)(fd))
#define WASI_P2_POLL(p, n, ms) WSAPoll((p), (ULONG)(n), (ms))
#define WASI_P2_RECV(fd, b, n, f) recv((SOCKET)(fd), (char *)(b), (int)(n), (f))
#define WASI_P2_SEND(fd, b, n, f) send((SOCKET)(fd), (const char *)(b), (int)(n), (f))
#define WASI_P2_RECVFROM(fd, b, n, f, a, l) recvfrom((SOCKET)(fd), (char *)(b), (int)(n), (f), (a), (l))
#define WASI_P2_SENDTO(fd, b, n, f, a, l) sendto((SOCKET)(fd), (const char *)(b), (int)(n), (f), (a), (l))
#define WASI_P2_SETSOCKOPT(fd, level, name, v, n) setsockopt((SOCKET)(fd), (level), (name), (const char *)(v), (int)(n))
#define WASI_P2_GETSOCKOPT(fd, level, name, v, n) getsockopt((SOCKET)(fd), (level), (name), (char *)(v), (n))
#define WASI_P2_CLOEXEC(fd) ((void)(fd))
#define WASI_P2_SOCKET(family, type) ((int)socket((family), (type), 0))
#define WASI_P2_ACCEPT(fd) ((int)accept((SOCKET)(fd), NULL, NULL))
#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif
#ifndef SHUT_RD
#define SHUT_RD SD_RECEIVE
#define SHUT_WR SD_SEND
#define SHUT_RDWR SD_BOTH
#endif
/* the number of a Winsock error as the `errno` that has the same meaning */
WASI_P2_FN int wasi_p2_wsa_errno(int e) {
    switch (e) {
    case WSAEWOULDBLOCK: return EWOULDBLOCK;
    case WSAEINPROGRESS: return EINPROGRESS;
    case WSAEALREADY: return EALREADY;
    case WSAEINTR: return EINTR;
    case WSAEACCES: return EACCES;
    case WSAEADDRINUSE: return EADDRINUSE;
    case WSAEADDRNOTAVAIL: return EADDRNOTAVAIL;
    case WSAEAFNOSUPPORT: return EAFNOSUPPORT;
    case WSAECONNABORTED: return ECONNABORTED;
    case WSAECONNREFUSED: return ECONNREFUSED;
    case WSAECONNRESET: return ECONNRESET;
    case WSAEHOSTUNREACH: return EHOSTUNREACH;
    case WSAEINVAL: return EINVAL;
    case WSAEISCONN: return EISCONN;
    case WSAEMFILE: return EMFILE;
    case WSAEMSGSIZE: return EMSGSIZE;
    case WSAENETDOWN: return ENETDOWN;
    case WSAENETUNREACH: return ENETUNREACH;
    case WSAENOBUFS: return ENOBUFS;
    case WSAENOPROTOOPT: return ENOPROTOOPT;
    case WSAENOTCONN: return ENOTCONN;
    case WSAEOPNOTSUPP: return EOPNOTSUPP;
    case WSAEPROTONOSUPPORT: return EPROTONOSUPPORT;
    case WSAETIMEDOUT: return ETIMEDOUT;
    case WSAESHUTDOWN: return EPIPE;
    case 0: return 0;
    default: return EIO;
    }
}
WASI_P2_FN int wasi_p2_errno(void) { return wasi_p2_wsa_errno(WSAGetLastError()); }
WASI_P2_FN int wasi_p2_sockerr(int e) { return wasi_p2_wsa_errno(e); } /* the value of SO_ERROR */
WASI_P2_FN void wasi_p2_net_start(void) {
    WSADATA data;
    WSAStartup(MAKEWORD(2, 2), &data); /* counted by the system: calling it again is harmless */
}
#else
#define WASI_P2_CLOSE(fd) close(fd)
#define WASI_P2_POLL(p, n, ms) poll((p), (n), (ms))
#define WASI_P2_RECV(fd, b, n, f) recv((fd), (b), (n), (f))
#define WASI_P2_SEND(fd, b, n, f) send((fd), (b), (n), (f))
#define WASI_P2_RECVFROM(fd, b, n, f, a, l) recvfrom((fd), (b), (n), (f), (a), (l))
#define WASI_P2_SENDTO(fd, b, n, f, a, l) sendto((fd), (b), (n), (f), (a), (l))
#define WASI_P2_SETSOCKOPT(fd, level, name, v, n) setsockopt((fd), (level), (name), (v), (n))
#define WASI_P2_GETSOCKOPT(fd, level, name, v, n) getsockopt((fd), (level), (name), (v), (n))
#define WASI_P2_CLOEXEC(fd) fcntl((fd), F_SETFD, FD_CLOEXEC)
#define WASI_P2_SOCKET(family, type) socket((family), (type), 0)
#define WASI_P2_ACCEPT(fd) accept((fd), NULL, NULL)
WASI_P2_FN int wasi_p2_errno(void) { return errno; }
WASI_P2_FN int wasi_p2_sockerr(int e) { return e; }
WASI_P2_FN void wasi_p2_net_start(void) {}
#endif

WASI_P2_FN int wasi_p2_net_errno(int e) {
    switch (e) {
    case EACCES: case EPERM: return WASI_P2_N_ACCESS_DENIED;
    case EAFNOSUPPORT: case EOPNOTSUPP: case ENOPROTOOPT: case EPROTONOSUPPORT: return WASI_P2_N_NOT_SUPPORTED;
    case ENOMEM: case ENOBUFS: return WASI_P2_N_OUT_OF_MEMORY;
    case ETIMEDOUT: return WASI_P2_N_TIMEOUT;
    case EALREADY: return WASI_P2_N_CONCURRENCY_CONFLICT;
    case EAGAIN: case EINPROGRESS: return WASI_P2_N_WOULD_BLOCK;
#if defined(EWOULDBLOCK) && EWOULDBLOCK != EAGAIN
    case EWOULDBLOCK: return WASI_P2_N_WOULD_BLOCK;
#endif
    case EMFILE: case ENFILE: return WASI_P2_N_NEW_SOCKET_LIMIT;
    case EADDRNOTAVAIL: return WASI_P2_N_ADDRESS_NOT_BINDABLE;
    case EADDRINUSE: return WASI_P2_N_ADDRESS_IN_USE;
    case EHOSTUNREACH: case ENETUNREACH: case ENETDOWN: return WASI_P2_N_REMOTE_UNREACHABLE;
#ifdef EHOSTDOWN
    case EHOSTDOWN: return WASI_P2_N_REMOTE_UNREACHABLE;
#endif
    case ECONNREFUSED: return WASI_P2_N_CONNECTION_REFUSED;
    case ECONNRESET: case EPIPE: return WASI_P2_N_CONNECTION_RESET;
    case ECONNABORTED: return WASI_P2_N_CONNECTION_ABORTED;
    case EMSGSIZE: return WASI_P2_N_DATAGRAM_TOO_LARGE;
    case ENOTCONN: case EISCONN: return WASI_P2_N_INVALID_STATE;
    case EINVAL: return WASI_P2_N_INVALID_ARGUMENT;
    default: return WASI_P2_N_UNKNOWN;
    }
}

/* an address: family 0 is IPv4 (v4: four bytes), 1 is IPv6 (v6: eight 16-bit numbers) */
typedef struct {
    int family;
    uint16_t port;
    uint8_t v4[4];
    uint16_t v6[8];
    uint32_t flow, scope;
} wasi_p2_addr;

/* from the flat arguments: the tag and eleven numbers */
WASI_P2_FN wasi_p2_addr wasi_p2_addr_flat(uint32_t tag, const uint32_t *f) {
    wasi_p2_addr a;
    memset(&a, 0, sizeof a);
    a.family = tag == 0 ? 0 : 1;
    a.port = (uint16_t)f[0];
    if (tag == 0) {
        for (int i = 0; i < 4; i++) a.v4[i] = (uint8_t)f[1 + i];
    } else {
        a.flow = f[1];
        for (int i = 0; i < 8; i++) a.v6[i] = (uint16_t)f[2 + i];
        a.scope = f[10];
    }
    return a;
}

WASI_P2_FN void wasi_p2_addr_text(const wasi_p2_addr *a, char *out, size_t n) {
    if (a->family == 0) {
        inet_ntop(AF_INET, a->v4, out, (socklen_t)n);
    } else {
        struct in6_addr x;
        for (int i = 0; i < 8; i++) {
            x.s6_addr[2 * i] = (uint8_t)(a->v6[i] >> 8);
            x.s6_addr[2 * i + 1] = (uint8_t)a->v6[i];
        }
        inet_ntop(AF_INET6, &x, out, (socklen_t)n);
    }
}

WASI_P2_FN socklen_t wasi_p2_to_sockaddr(const wasi_p2_addr *a, struct sockaddr_storage *ss) {
    memset(ss, 0, sizeof *ss);
    if (a->family == 0) {
        struct sockaddr_in *in = (struct sockaddr_in *)ss;
        in->sin_family = AF_INET;
        in->sin_port = htons(a->port);
        memcpy(&in->sin_addr, a->v4, 4);
        return sizeof *in;
    }
    struct sockaddr_in6 *in6 = (struct sockaddr_in6 *)ss;
    in6->sin6_family = AF_INET6;
    in6->sin6_port = htons(a->port);
    in6->sin6_flowinfo = htonl(a->flow);
    in6->sin6_scope_id = a->scope;
    for (int i = 0; i < 8; i++) {
        in6->sin6_addr.s6_addr[2 * i] = (uint8_t)(a->v6[i] >> 8);
        in6->sin6_addr.s6_addr[2 * i + 1] = (uint8_t)a->v6[i];
    }
    return sizeof *in6;
}

WASI_P2_FN wasi_p2_addr wasi_p2_from_sockaddr(const struct sockaddr_storage *ss) {
    wasi_p2_addr a;
    memset(&a, 0, sizeof a);
    if (ss->ss_family == AF_INET) {
        const struct sockaddr_in *in = (const struct sockaddr_in *)ss;
        a.family = 0;
        a.port = ntohs(in->sin_port);
        memcpy(a.v4, &in->sin_addr, 4);
    } else {
        const struct sockaddr_in6 *in6 = (const struct sockaddr_in6 *)ss;
        a.family = 1;
        a.port = ntohs(in6->sin6_port);
        a.flow = ntohl(in6->sin6_flowinfo);
        a.scope = in6->sin6_scope_id;
        for (int i = 0; i < 8; i++) a.v6[i] = (uint16_t)(in6->sin6_addr.s6_addr[2 * i] << 8 | in6->sin6_addr.s6_addr[2 * i + 1]);
    }
    return a;
}

WASI_P2_FN int wasi_p2_addr_unspecified(const wasi_p2_addr *a) {
    if (a->family == 0) return !(a->v4[0] | a->v4[1] | a->v4[2] | a->v4[3]);
    for (int i = 0; i < 8; i++)
        if (a->v6[i]) return 0;
    return 1;
}

/* a unicast address: not multicast, not the broadcast, not an IPv4-mapped IPv6 address (the unspecified address is allowed here) */
WASI_P2_FN int wasi_p2_addr_unicast(const wasi_p2_addr *a) {
    if (a->family == 0) return !(a->v4[0] >= 224 && a->v4[0] <= 239) && !(a->v4[0] == 255 && a->v4[1] == 255 && a->v4[2] == 255 && a->v4[3] == 255);
    if ((a->v6[0] >> 8) == 0xff) return 0;
    if (!a->v6[0] && !a->v6[1] && !a->v6[2] && !a->v6[3] && !a->v6[4] && a->v6[5] == 0xffff) return 0;
    return 1;
}

/* the address in memory: the variant of 32 bytes at `ptr` */
WASI_P2_FN void wasi_p2_write_addr(wasi_p2_state *s, uint32_t comp, uint32_t ptr, const wasi_p2_addr *a) {
    wasi_p2_store_u8(s, comp, ptr, (uint8_t)a->family);
    wasi_p2_store_u16(s, comp, ptr + 4, a->port);
    if (a->family == 0) {
        memcpy(wasi_p2_mem(s, comp, ptr + 6, 4), a->v4, 4);
    } else {
        wasi_p2_store_u32(s, comp, ptr + 8, a->flow);
        for (int i = 0; i < 8; i++) wasi_p2_store_u16(s, comp, ptr + 12 + 2 * i, a->v6[i]);
        wasi_p2_store_u32(s, comp, ptr + 28, a->scope);
    }
}

WASI_P2_FN wasi_p2_addr wasi_p2_read_addr(wasi_p2_state *s, uint32_t comp, uint32_t ptr) {
    wasi_p2_addr a;
    memset(&a, 0, sizeof a);
    a.family = wasi_p2_load_u8(s, comp, ptr) == 0 ? 0 : 1;
    a.port = wasi_p2_load_u16(s, comp, ptr + 4);
    if (a.family == 0) {
        memcpy(a.v4, wasi_p2_mem(s, comp, ptr + 6, 4), 4);
    } else {
        a.flow = wasi_p2_load_u32(s, comp, ptr + 8);
        for (int i = 0; i < 8; i++) a.v6[i] = wasi_p2_load_u16(s, comp, ptr + 12 + 2 * i);
        a.scope = wasi_p2_load_u32(s, comp, ptr + 28);
    }
    return a;
}

/* results */

WASI_P2_FN void wasi_p2_net_status(wasi_p2_state *s, uint32_t comp, uint32_t retptr, int rc) {
    if (rc != WASI_P2_NOK) {
        wasi_p2_store_u8(s, comp, retptr, 1);
        wasi_p2_store_u8(s, comp, retptr + 1, (uint8_t)rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
}

WASI_P2_FN void wasi_p2_net_fail(wasi_p2_state *s, uint32_t comp, uint32_t retptr, uint32_t at, int rc) {
    wasi_p2_store_u8(s, comp, retptr, 1);
    wasi_p2_store_u8(s, comp, at, (uint8_t)rc);
}

/* the objects */

typedef struct {
    int fd, family, state;
    uint32_t backlog;
    int recv_shut, send_shut;
    int refs; /* the handle of the socket and every stream of it */
} wasi_p2_tcp;

typedef struct {
    int fd, family, state, closed;
    int has_remote;
    wasi_p2_addr remote;
    int refs;
} wasi_p2_udp;

typedef struct {
    wasi_p2_udp *u;
    uint32_t permit; /* outgoing only */
} wasi_p2_dgram_stream;

typedef struct {
    wasi_p2_addr *list;
    uint32_t count, pos;
} wasi_p2_resolved;

WASI_P2_FN int wasi_p2_set_nonblock(int fd) {
#ifdef _WIN32
    u_long on = 1;
    return ioctlsocket((SOCKET)fd, FIONBIO, &on) == 0 ? 0 : -1;
#else
    int fl = fcntl(fd, F_GETFL, 0);
    return fl < 0 || fcntl(fd, F_SETFL, fl | O_NONBLOCK) < 0 ? -1 : 0;
#endif
}

WASI_P2_FN int wasi_p2_poll_fd(int fd, short events) {
    struct pollfd p = {fd, events, 0};
    return WASI_P2_POLL(&p, 1, 0) > 0;
}

/* a socket of the given family and type: the descriptor, or -1 and the network error in *rc */
WASI_P2_FN int wasi_p2_net_socket(int family, int type, int *rc) {
    wasi_p2_net_start();
    int fd = WASI_P2_SOCKET(family == 0 ? AF_INET : AF_INET6, type);
    if (fd < 0) {
        *rc = wasi_p2_net_errno(wasi_p2_errno());
        return -1;
    }
    if (wasi_p2_set_nonblock(fd) < 0) {
        *rc = wasi_p2_net_errno(wasi_p2_errno());
        WASI_P2_CLOSE(fd);
        return -1;
    }
    int on = 1;
    if (family == 1) WASI_P2_SETSOCKOPT(fd, IPPROTO_IPV6, IPV6_V6ONLY, &on, sizeof on);
    WASI_P2_CLOEXEC(fd);
    return fd;
}

WASI_P2_FN void wasi_p2_tcp_unref(wasi_p2_state *s, wasi_p2_tcp *t) {
    (void)s;
    if (--t->refs == 0) free(t);
}

WASI_P2_FN void wasi_p2_udp_unref(wasi_p2_state *s, wasi_p2_udp *u) {
    (void)s;
    if (--u->refs == 0) free(u);
}

WASI_P2_FN void wasi_p2_tcp_destroy(wasi_p2_state *s, void *obj) { /* the handle of the socket is dropped, or the state is freed */
    wasi_p2_tcp *t = (wasi_p2_tcp *)obj;
    if (t->fd >= 0) WASI_P2_CLOSE(t->fd);
    t->fd = -1;
    t->state = WASI_P2_SS_CLOSED;
    wasi_p2_tcp_unref(s, t);
}

WASI_P2_FN void wasi_p2_udp_destroy(wasi_p2_state *s, void *obj) {
    wasi_p2_udp *u = (wasi_p2_udp *)obj;
    if (u->fd >= 0) WASI_P2_CLOSE(u->fd);
    u->fd = -1;
    u->closed = 1;
    wasi_p2_udp_unref(s, u);
}

WASI_P2_FN wasi_p2_tcp *wasi_p2_tcp_get(wasi_p2_state *s, uint32_t h) {
    return (wasi_p2_tcp *)wasi_p2_table_get(s, h, WASI_P2_KIND_TCP_SOCKET)->obj;
}
WASI_P2_FN wasi_p2_udp *wasi_p2_udp_get(wasi_p2_state *s, uint32_t h) {
    return (wasi_p2_udp *)wasi_p2_table_get(s, h, WASI_P2_KIND_UDP_SOCKET)->obj;
}
WASI_P2_FN void wasi_p2_network_get(wasi_p2_state *s, uint32_t h) { wasi_p2_table_get(s, h, WASI_P2_KIND_NETWORK); }

/* policy and the checks of an address */
WASI_P2_FN int wasi_p2_policy(wasi_p2_state *s, const wasi_p2_addr *a, int use) {
    char text[64];
    wasi_p2_addr_text(a, text, sizeof text);
    return s->socket_addr_check && s->socket_addr_check(s, text, a->port, use) ? WASI_P2_NOK : WASI_P2_N_ACCESS_DENIED;
}

WASI_P2_FN int wasi_p2_check_bind(wasi_p2_state *s, int family, const wasi_p2_addr *a, int use) {
    if (a->family != family || !wasi_p2_addr_unicast(a)) return WASI_P2_N_INVALID_ARGUMENT;
    return wasi_p2_policy(s, a, use);
}

WASI_P2_FN int wasi_p2_check_connect(wasi_p2_state *s, int family, const wasi_p2_addr *a, int use) {
    if (a->family != family || !wasi_p2_addr_unicast(a) || wasi_p2_addr_unspecified(a) || a->port == 0) return WASI_P2_N_INVALID_ARGUMENT;
    return wasi_p2_policy(s, a, use);
}

/* network */

WASI_P2_FN void wasi_sockets_network_network_drop(wasi_p2_state *s, uint32_t h) { wasi_p2_table_drop(s, h, WASI_P2_KIND_NETWORK); }

WASI_P2_FN void wasi_sockets_network_network_error_code(wasi_p2_state *s, uint32_t comp, uint32_t err, uint32_t retptr) {
    wasi_p2_error *e = (wasi_p2_error *)wasi_p2_table_get(s, err, WASI_P2_KIND_ERROR)->obj;
    if (e->network_code < 0) {
        wasi_p2_store_u8(s, comp, retptr, 0);
        return;
    }
    wasi_p2_store_u8(s, comp, retptr, 1);
    wasi_p2_store_u8(s, comp, retptr + 1, (uint8_t)e->network_code);
}

WASI_P2_FN uint32_t wasi_sockets_instance_network_instance_network(wasi_p2_state *s) {
    return wasi_p2_table_new(s, WASI_P2_KIND_NETWORK, NULL, NULL);
}

/* the streams of a connection */

typedef struct {
    wasi_p2_stream base;
    wasi_p2_tcp *t;
} wasi_p2_sock_stream;

WASI_P2_FN void wasi_p2_sock_stream_destroy(wasi_p2_state *s, wasi_p2_stream *st) {
    wasi_p2_tcp_unref(s, ((wasi_p2_sock_stream *)st)->t);
    wasi_p2_stream_free(s, st);
}

WASI_P2_FN void wasi_p2_sock_fail(wasi_p2_stream *st, int e, const char *what) {
    st->failure = what;
    st->failure_has_network = 1;
    st->failure_network_code = wasi_p2_net_errno(e);
}

WASI_P2_FN int wasi_p2_sock_read(wasi_p2_state *s, wasi_p2_stream *st, uint8_t *buf, uint64_t len, uint64_t *got) {
    wasi_p2_tcp *t = ((wasi_p2_sock_stream *)st)->t;
    (void)s;
    *got = 0;
    if (t->recv_shut || t->state == WASI_P2_SS_CLOSED) return WASI_P2_STREAM_CLOSED;
    if (len == 0) return WASI_P2_STREAM_OK;
    ssize_t n = WASI_P2_RECV(t->fd, buf, (size_t)len, 0);
    if (n < 0) {
        if (wasi_p2_errno() == EAGAIN || wasi_p2_errno() == EWOULDBLOCK) return WASI_P2_STREAM_OK;
        wasi_p2_sock_fail(st, wasi_p2_errno(), "read failed");
        return WASI_P2_STREAM_FAILED;
    }
    if (n == 0) return WASI_P2_STREAM_CLOSED;
    *got = (uint64_t)n;
    return WASI_P2_STREAM_OK;
}

WASI_P2_FN int wasi_p2_sock_in_ready(wasi_p2_state *s, wasi_p2_stream *st) {
    wasi_p2_tcp *t = ((wasi_p2_sock_stream *)st)->t;
    (void)s;
    return t->recv_shut || t->state == WASI_P2_SS_CLOSED || wasi_p2_poll_fd(t->fd, POLLIN);
}

WASI_P2_FN uint64_t wasi_p2_sock_check_write(wasi_p2_state *s, wasi_p2_stream *st, int *status) {
    wasi_p2_tcp *t = ((wasi_p2_sock_stream *)st)->t;
    (void)s;
    *status = t->send_shut || t->state == WASI_P2_SS_CLOSED ? WASI_P2_STREAM_CLOSED : WASI_P2_STREAM_OK;
    return *status == WASI_P2_STREAM_OK ? WASI_P2_SOCK_CHUNK : 0;
}

WASI_P2_FN int wasi_p2_sock_write(wasi_p2_state *s, wasi_p2_stream *st, const uint8_t *data, uint64_t len) {
    wasi_p2_tcp *t = ((wasi_p2_sock_stream *)st)->t;
    (void)s;
    while (len) {
        ssize_t n = WASI_P2_SEND(t->fd, data, (size_t)len, MSG_NOSIGNAL);
        if (n < 0) {
            if (wasi_p2_errno() == EAGAIN || wasi_p2_errno() == EWOULDBLOCK) { /* the system buffer is full: wait for room */
                struct pollfd p = {t->fd, POLLOUT, 0};
                WASI_P2_POLL(&p, 1, 50);
                continue;
            }
            if (wasi_p2_errno() == EINTR) continue;
            wasi_p2_sock_fail(st, wasi_p2_errno(), "write failed");
            return WASI_P2_STREAM_FAILED;
        }
        data += n;
        len -= (uint64_t)n;
    }
    return WASI_P2_STREAM_OK;
}

WASI_P2_FN int wasi_p2_sock_flush(wasi_p2_state *s, wasi_p2_stream *st) {
    (void)s, (void)st;
    return WASI_P2_STREAM_OK;
}

WASI_P2_FN int wasi_p2_sock_out_ready(wasi_p2_state *s, wasi_p2_stream *st) {
    wasi_p2_tcp *t = ((wasi_p2_sock_stream *)st)->t;
    (void)s;
    return t->send_shut || t->state == WASI_P2_SS_CLOSED || wasi_p2_poll_fd(t->fd, POLLOUT);
}

WASI_P2_FN uint32_t wasi_p2_sock_stream_new(wasi_p2_state *s, wasi_p2_tcp *t, int output) {
    wasi_p2_sock_stream *st = (wasi_p2_sock_stream *)calloc(1, sizeof *st);
    if (!st) s->trap(s, "out of memory");
    st->t = t;
    t->refs++;
    st->base.destroy = wasi_p2_sock_stream_destroy;
    if (output) {
        st->base.check_write = wasi_p2_sock_check_write;
        st->base.write = wasi_p2_sock_write;
        st->base.flush = wasi_p2_sock_flush;
        st->base.ready = wasi_p2_sock_out_ready;
        return wasi_p2_output_stream_new(s, &st->base);
    }
    st->base.read = wasi_p2_sock_read;
    st->base.ready = wasi_p2_sock_in_ready;
    return wasi_p2_input_stream_new(s, &st->base);
}

/* tcp-create-socket */

WASI_P2_FN wasi_p2_tcp *wasi_p2_tcp_make(wasi_p2_state *s, int family, int fd, int state) {
    wasi_p2_tcp *t = (wasi_p2_tcp *)calloc(1, sizeof *t);
    if (!t) s->trap(s, "out of memory");
    t->fd = fd, t->family = family, t->state = state, t->backlog = 128, t->refs = 1;
    return t;
}

WASI_P2_FN void wasi_sockets_tcp_create_socket_create_tcp_socket(wasi_p2_state *s, uint32_t comp, uint32_t address_family, uint32_t retptr) {
    int rc = WASI_P2_NOK;
    int fd = wasi_p2_net_socket((int)address_family, SOCK_STREAM, &rc);
    if (fd < 0) {
        wasi_p2_net_fail(s, comp, retptr, retptr + 4, rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u32(s, comp, retptr + 4,
                      wasi_p2_table_new(s, WASI_P2_KIND_TCP_SOCKET, wasi_p2_tcp_make(s, (int)address_family, fd, WASI_P2_SS_UNBOUND), wasi_p2_tcp_destroy));
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_drop(wasi_p2_state *s, uint32_t h) {
    wasi_p2_tcp_get(s, h);
    wasi_p2_table_drop(s, h, WASI_P2_KIND_TCP_SOCKET);
}

WASI_P2_FN int wasi_p2_tcp_open(const wasi_p2_tcp *t) { return t->state == WASI_P2_SS_CLOSED ? WASI_P2_N_INVALID_STATE : WASI_P2_NOK; }

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_start_bind(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t network, uint32_t tag, uint32_t p1, uint32_t p2,
                                                       uint32_t p3, uint32_t p4, uint32_t p5, uint32_t p6, uint32_t p7, uint32_t p8, uint32_t p9, uint32_t p10,
                                                       uint32_t p11, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    wasi_p2_network_get(s, network);
    uint32_t f[11] = {p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11};
    wasi_p2_addr a = wasi_p2_addr_flat(tag, f);
    int rc = WASI_P2_NOK;
    if (t->state != WASI_P2_SS_UNBOUND) rc = WASI_P2_N_INVALID_STATE;
    if (rc == WASI_P2_NOK) rc = wasi_p2_check_bind(s, t->family, &a, WASI_P2_USE_TCP_BIND);
    if (rc == WASI_P2_NOK) {
#ifdef _WIN32
        /* SO_REUSEADDR on Windows lets another program take the port; the address is made exclusive instead */
        int on = 1;
        WASI_P2_SETSOCKOPT(t->fd, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, &on, sizeof on);
#else
        int on = 1;
        WASI_P2_SETSOCKOPT(t->fd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof on);
#endif
        struct sockaddr_storage ss;
        socklen_t n = wasi_p2_to_sockaddr(&a, &ss);
        if (bind(t->fd, (struct sockaddr *)&ss, n) < 0) rc = wasi_p2_net_errno(wasi_p2_errno());
        else t->state = WASI_P2_SS_BIND_IN_PROGRESS;
    }
    wasi_p2_net_status(s, comp, retptr, rc);
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_finish_bind(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = WASI_P2_NOK;
    if (t->state != WASI_P2_SS_BIND_IN_PROGRESS) rc = WASI_P2_N_NOT_IN_PROGRESS;
    else t->state = WASI_P2_SS_BOUND;
    wasi_p2_net_status(s, comp, retptr, rc);
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_start_connect(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t network, uint32_t tag, uint32_t p1,
                                                          uint32_t p2, uint32_t p3, uint32_t p4, uint32_t p5, uint32_t p6, uint32_t p7, uint32_t p8, uint32_t p9,
                                                          uint32_t p10, uint32_t p11, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    wasi_p2_network_get(s, network);
    uint32_t f[11] = {p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11};
    wasi_p2_addr a = wasi_p2_addr_flat(tag, f);
    int rc = WASI_P2_NOK;
    if (t->state != WASI_P2_SS_UNBOUND && t->state != WASI_P2_SS_BOUND) rc = WASI_P2_N_INVALID_STATE;
    if (rc == WASI_P2_NOK) rc = wasi_p2_check_connect(s, t->family, &a, WASI_P2_USE_TCP_CONNECT);
    if (rc == WASI_P2_NOK) {
        struct sockaddr_storage ss;
        socklen_t n = wasi_p2_to_sockaddr(&a, &ss);
        if (connect(t->fd, (struct sockaddr *)&ss, n) < 0 && wasi_p2_errno() != EINPROGRESS && wasi_p2_errno() != EWOULDBLOCK) {
            rc = wasi_p2_net_errno(wasi_p2_errno());
            t->state = WASI_P2_SS_CLOSED;
        } else {
            t->state = WASI_P2_SS_CONNECT_IN_PROGRESS;
        }
    }
    wasi_p2_net_status(s, comp, retptr, rc);
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_finish_connect(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = WASI_P2_NOK;
    if (t->state != WASI_P2_SS_CONNECT_IN_PROGRESS) {
        rc = WASI_P2_N_NOT_IN_PROGRESS;
    } else if (!wasi_p2_poll_fd(t->fd, POLLOUT)) {
        rc = WASI_P2_N_WOULD_BLOCK;
    } else {
        int err = 0;
        socklen_t n = sizeof err;
        WASI_P2_GETSOCKOPT(t->fd, SOL_SOCKET, SO_ERROR, &err, &n);
        if (err) {
            t->state = WASI_P2_SS_CLOSED;
            rc = wasi_p2_net_errno(wasi_p2_sockerr(err));
        } else {
            t->state = WASI_P2_SS_CONNECTED;
        }
    }
    if (rc != WASI_P2_NOK) {
        wasi_p2_net_fail(s, comp, retptr, retptr + 4, rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u32(s, comp, retptr + 4, wasi_p2_sock_stream_new(s, t, 0));
    wasi_p2_store_u32(s, comp, retptr + 8, wasi_p2_sock_stream_new(s, t, 1));
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_start_listen(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = WASI_P2_NOK;
    if (t->state != WASI_P2_SS_BOUND) rc = WASI_P2_N_INVALID_STATE;
    else if (listen(t->fd, (int)t->backlog) < 0) rc = wasi_p2_net_errno(wasi_p2_errno());
    else t->state = WASI_P2_SS_LISTEN_IN_PROGRESS;
    wasi_p2_net_status(s, comp, retptr, rc);
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_finish_listen(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = WASI_P2_NOK;
    if (t->state != WASI_P2_SS_LISTEN_IN_PROGRESS) rc = WASI_P2_N_NOT_IN_PROGRESS;
    else t->state = WASI_P2_SS_LISTENING;
    wasi_p2_net_status(s, comp, retptr, rc);
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_accept(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = WASI_P2_NOK, fd = -1;
    if (t->state != WASI_P2_SS_LISTENING) {
        rc = WASI_P2_N_INVALID_STATE;
    } else {
        fd = WASI_P2_ACCEPT(t->fd);
        if (fd < 0) rc = wasi_p2_errno() == EAGAIN || wasi_p2_errno() == EWOULDBLOCK ? WASI_P2_N_WOULD_BLOCK : wasi_p2_net_errno(wasi_p2_errno());
        else if (wasi_p2_set_nonblock(fd) < 0) rc = wasi_p2_net_errno(wasi_p2_errno());
    }
    if (rc != WASI_P2_NOK) {
        if (fd >= 0) WASI_P2_CLOSE(fd);
        wasi_p2_net_fail(s, comp, retptr, retptr + 4, rc);
        return;
    }
    WASI_P2_CLOEXEC(fd);
    wasi_p2_tcp *conn = wasi_p2_tcp_make(s, t->family, fd, WASI_P2_SS_CONNECTED);
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u32(s, comp, retptr + 4, wasi_p2_table_new(s, WASI_P2_KIND_TCP_SOCKET, conn, wasi_p2_tcp_destroy));
    wasi_p2_store_u32(s, comp, retptr + 8, wasi_p2_sock_stream_new(s, conn, 0));
    wasi_p2_store_u32(s, comp, retptr + 12, wasi_p2_sock_stream_new(s, conn, 1));
}

WASI_P2_FN void wasi_p2_address_result(wasi_p2_state *s, uint32_t comp, uint32_t retptr, int rc, const wasi_p2_addr *a) {
    if (rc != WASI_P2_NOK) {
        wasi_p2_net_fail(s, comp, retptr, retptr + 4, rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_write_addr(s, comp, retptr + 4, a);
}

WASI_P2_FN int wasi_p2_name_of(int fd, int peer, wasi_p2_addr *out) {
    struct sockaddr_storage ss;
    socklen_t n = sizeof ss;
    if ((peer ? getpeername(fd, (struct sockaddr *)&ss, &n) : getsockname(fd, (struct sockaddr *)&ss, &n)) < 0) return wasi_p2_net_errno(wasi_p2_errno());
    *out = wasi_p2_from_sockaddr(&ss);
    return WASI_P2_NOK;
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_local_address(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    wasi_p2_addr a;
    memset(&a, 0, sizeof a);
    int rc = t->state == WASI_P2_SS_UNBOUND || t->state == WASI_P2_SS_BIND_IN_PROGRESS || t->state == WASI_P2_SS_CLOSED ? WASI_P2_N_INVALID_STATE
                                                                                                                         : wasi_p2_name_of(t->fd, 0, &a);
    wasi_p2_address_result(s, comp, retptr, rc, &a);
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_remote_address(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    wasi_p2_addr a;
    memset(&a, 0, sizeof a);
    int rc = t->state != WASI_P2_SS_CONNECTED ? WASI_P2_N_INVALID_STATE : wasi_p2_name_of(t->fd, 1, &a);
    wasi_p2_address_result(s, comp, retptr, rc, &a);
}

WASI_P2_FN uint32_t wasi_sockets_tcp_tcp_socket_is_listening(wasi_p2_state *s, uint32_t self) { return wasi_p2_tcp_get(s, self)->state == WASI_P2_SS_LISTENING; }

WASI_P2_FN uint32_t wasi_sockets_tcp_tcp_socket_address_family(wasi_p2_state *s, uint32_t self) { return (uint32_t)wasi_p2_tcp_get(s, self)->family; }

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_set_listen_backlog_size(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t value, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = wasi_p2_tcp_open(t);
    if (rc == WASI_P2_NOK && value == 0) rc = WASI_P2_N_INVALID_ARGUMENT;
    if (rc == WASI_P2_NOK && (t->state == WASI_P2_SS_CONNECT_IN_PROGRESS || t->state == WASI_P2_SS_CONNECTED)) rc = WASI_P2_N_INVALID_STATE;
    if (rc == WASI_P2_NOK) {
        t->backlog = value < WASI_P2_BACKLOG_MAX ? (uint32_t)value : WASI_P2_BACKLOG_MAX;
        if (t->state == WASI_P2_SS_LISTENING && listen(t->fd, (int)t->backlog) < 0) rc = wasi_p2_net_errno(wasi_p2_errno());
    }
    wasi_p2_net_status(s, comp, retptr, rc);
}

/* options: numbers from getsockopt / to setsockopt; the names that a system lacks are `not-supported` */

WASI_P2_FN int wasi_p2_getopt(int fd, int level, int name, int *value) {
    socklen_t n = sizeof *value;
    return WASI_P2_GETSOCKOPT(fd, level, name, value, &n) < 0 ? wasi_p2_net_errno(wasi_p2_errno()) : WASI_P2_NOK;
}

WASI_P2_FN int wasi_p2_setopt(int fd, int level, int name, int value) {
    return WASI_P2_SETSOCKOPT(fd, level, name, &value, sizeof value) < 0 ? wasi_p2_net_errno(wasi_p2_errno()) : WASI_P2_NOK;
}

#ifdef TCP_KEEPIDLE
#define WASI_P2_KEEPIDLE TCP_KEEPIDLE
#elif defined(TCP_KEEPALIVE)
#define WASI_P2_KEEPIDLE TCP_KEEPALIVE
#endif

WASI_P2_FN int wasi_p2_seconds(uint64_t ns) {
    uint64_t sec = (ns + 999999999ULL) / 1000000000ULL;
    return sec < 1 ? 1 : sec > 2147483647ULL ? 2147483647 : (int)sec;
}

/* result<number>: the value stored at `at` with `size` bytes (1, 4 or 8) */
WASI_P2_FN void wasi_p2_number_result(wasi_p2_state *s, uint32_t comp, uint32_t retptr, uint32_t at, int size, int rc, uint64_t value) {
    if (rc != WASI_P2_NOK) {
        wasi_p2_net_fail(s, comp, retptr, retptr + at, rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    if (size == 1) wasi_p2_store_u8(s, comp, retptr + at, (uint8_t)value);
    else if (size == 4) wasi_p2_store_u32(s, comp, retptr + at, (uint32_t)value);
    else wasi_p2_store_u64(s, comp, retptr + at, value);
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_keep_alive_enabled(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int v = 0, rc = wasi_p2_tcp_open(t);
    if (rc == WASI_P2_NOK) rc = wasi_p2_getopt(t->fd, SOL_SOCKET, SO_KEEPALIVE, &v);
    wasi_p2_number_result(s, comp, retptr, 1, 1, rc, v != 0);
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_set_keep_alive_enabled(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t value, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = wasi_p2_tcp_open(t);
    if (rc == WASI_P2_NOK) rc = wasi_p2_setopt(t->fd, SOL_SOCKET, SO_KEEPALIVE, value != 0);
    wasi_p2_net_status(s, comp, retptr, rc);
}

/* `name` < 0: the system has no such option */
WASI_P2_FN void wasi_p2_keepalive_get(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr, int name, uint64_t factor, int size) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int v = 0, rc = wasi_p2_tcp_open(t);
    if (rc == WASI_P2_NOK && name < 0) rc = WASI_P2_N_NOT_SUPPORTED;
    if (rc == WASI_P2_NOK) rc = wasi_p2_getopt(t->fd, IPPROTO_TCP, name, &v);
    wasi_p2_number_result(s, comp, retptr, size == 8 ? 8 : 4, size, rc, (uint64_t)v * factor);
}

WASI_P2_FN void wasi_p2_keepalive_set(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr, int name, uint64_t value, int seconds) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = wasi_p2_tcp_open(t);
    if (rc == WASI_P2_NOK && value == 0) rc = WASI_P2_N_INVALID_ARGUMENT;
    if (rc == WASI_P2_NOK && name < 0) rc = WASI_P2_N_NOT_SUPPORTED;
    if (rc == WASI_P2_NOK) rc = wasi_p2_setopt(t->fd, IPPROTO_TCP, name, seconds ? wasi_p2_seconds(value) : (int)(value < 2147483647ULL ? value : 2147483647ULL));
    wasi_p2_net_status(s, comp, retptr, rc);
}

#ifdef WASI_P2_KEEPIDLE
#define WASI_P2_OPT_IDLE WASI_P2_KEEPIDLE
#else
#define WASI_P2_OPT_IDLE (-1)
#endif
#ifdef TCP_KEEPINTVL
#define WASI_P2_OPT_INTVL TCP_KEEPINTVL
#else
#define WASI_P2_OPT_INTVL (-1)
#endif
#ifdef TCP_KEEPCNT
#define WASI_P2_OPT_CNT TCP_KEEPCNT
#else
#define WASI_P2_OPT_CNT (-1)
#endif

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_keep_alive_idle_time(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_keepalive_get(s, comp, self, retptr, WASI_P2_OPT_IDLE, 1000000000ULL, 8);
}
WASI_P2_FN void wasi_sockets_tcp_tcp_socket_set_keep_alive_idle_time(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t value, uint32_t retptr) {
    wasi_p2_keepalive_set(s, comp, self, retptr, WASI_P2_OPT_IDLE, value, 1);
}
WASI_P2_FN void wasi_sockets_tcp_tcp_socket_keep_alive_interval(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_keepalive_get(s, comp, self, retptr, WASI_P2_OPT_INTVL, 1000000000ULL, 8);
}
WASI_P2_FN void wasi_sockets_tcp_tcp_socket_set_keep_alive_interval(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t value, uint32_t retptr) {
    wasi_p2_keepalive_set(s, comp, self, retptr, WASI_P2_OPT_INTVL, value, 1);
}
WASI_P2_FN void wasi_sockets_tcp_tcp_socket_keep_alive_count(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_keepalive_get(s, comp, self, retptr, WASI_P2_OPT_CNT, 1, 4);
}
WASI_P2_FN void wasi_sockets_tcp_tcp_socket_set_keep_alive_count(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t value, uint32_t retptr) {
    wasi_p2_keepalive_set(s, comp, self, retptr, WASI_P2_OPT_CNT, value, 0);
}

WASI_P2_FN int wasi_p2_hop_get(int fd, int family, int *v) {
    int rc = family == 0 ? wasi_p2_getopt(fd, IPPROTO_IP, IP_TTL, v) : wasi_p2_getopt(fd, IPPROTO_IPV6, IPV6_UNICAST_HOPS, v);
    if (rc == WASI_P2_NOK && *v > 255) *v = 255;
    return rc;
}

WASI_P2_FN int wasi_p2_hop_set(int fd, int family, uint32_t value) {
    if ((value & 0xFF) == 0) return WASI_P2_N_INVALID_ARGUMENT;
    return family == 0 ? wasi_p2_setopt(fd, IPPROTO_IP, IP_TTL, (int)(value & 0xFF)) : wasi_p2_setopt(fd, IPPROTO_IPV6, IPV6_UNICAST_HOPS, (int)(value & 0xFF));
}

WASI_P2_FN int wasi_p2_buffer_set(int fd, int name, uint64_t value) {
    if (value == 0) return WASI_P2_N_INVALID_ARGUMENT;
    return wasi_p2_setopt(fd, SOL_SOCKET, name, (int)(value < 2147483647ULL ? value : 2147483647ULL));
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_hop_limit(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int v = 0, rc = wasi_p2_tcp_open(t);
    if (rc == WASI_P2_NOK) rc = wasi_p2_hop_get(t->fd, t->family, &v);
    wasi_p2_number_result(s, comp, retptr, 1, 1, rc, (uint64_t)v);
}
WASI_P2_FN void wasi_sockets_tcp_tcp_socket_set_hop_limit(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t value, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = wasi_p2_tcp_open(t);
    if (rc == WASI_P2_NOK) rc = wasi_p2_hop_set(t->fd, t->family, value);
    wasi_p2_net_status(s, comp, retptr, rc);
}
WASI_P2_FN void wasi_sockets_tcp_tcp_socket_receive_buffer_size(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int v = 0, rc = wasi_p2_tcp_open(t);
    if (rc == WASI_P2_NOK) rc = wasi_p2_getopt(t->fd, SOL_SOCKET, SO_RCVBUF, &v);
    wasi_p2_number_result(s, comp, retptr, 8, 8, rc, (uint64_t)v);
}
WASI_P2_FN void wasi_sockets_tcp_tcp_socket_set_receive_buffer_size(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t value, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = wasi_p2_tcp_open(t);
    if (rc == WASI_P2_NOK) rc = wasi_p2_buffer_set(t->fd, SO_RCVBUF, value);
    wasi_p2_net_status(s, comp, retptr, rc);
}
WASI_P2_FN void wasi_sockets_tcp_tcp_socket_send_buffer_size(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int v = 0, rc = wasi_p2_tcp_open(t);
    if (rc == WASI_P2_NOK) rc = wasi_p2_getopt(t->fd, SOL_SOCKET, SO_SNDBUF, &v);
    wasi_p2_number_result(s, comp, retptr, 8, 8, rc, (uint64_t)v);
}
WASI_P2_FN void wasi_sockets_tcp_tcp_socket_set_send_buffer_size(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t value, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = wasi_p2_tcp_open(t);
    if (rc == WASI_P2_NOK) rc = wasi_p2_buffer_set(t->fd, SO_SNDBUF, value);
    wasi_p2_net_status(s, comp, retptr, rc);
}

/* a pollable that asks a socket */
typedef struct {
    int kind; /* 0 tcp, 1 udp readable, 2 udp writable, 3 udp either, 4 always */
    wasi_p2_tcp *t;
    wasi_p2_udp *u;
} wasi_p2_sock_poll;

WASI_P2_FN int wasi_p2_sock_poll_ready(wasi_p2_state *s, wasi_p2_pollable *p) {
    wasi_p2_sock_poll *sp = (wasi_p2_sock_poll *)p->ctx;
    (void)s;
    switch (sp->kind) {
    case 0:
        if (sp->t->state == WASI_P2_SS_CONNECT_IN_PROGRESS) return wasi_p2_poll_fd(sp->t->fd, POLLOUT);
        if (sp->t->state == WASI_P2_SS_LISTENING) return wasi_p2_poll_fd(sp->t->fd, POLLIN);
        return 1;
    case 1: return wasi_p2_poll_fd(sp->u->fd, POLLIN);
    case 2: return wasi_p2_poll_fd(sp->u->fd, POLLOUT);
    case 3: return wasi_p2_poll_fd(sp->u->fd, POLLIN) || wasi_p2_poll_fd(sp->u->fd, POLLOUT);
    default: return 1;
    }
}

/* the pollable owns a reference to the socket (so that it can ask it), released when the pollable is dropped */
WASI_P2_FN void wasi_p2_sock_poll_destroy(wasi_p2_state *s, void *obj) {
    wasi_p2_pollable *p = (wasi_p2_pollable *)obj;
    wasi_p2_sock_poll *sp = (wasi_p2_sock_poll *)p->ctx;
    if (sp->t) wasi_p2_tcp_unref(s, sp->t);
    if (sp->u) wasi_p2_udp_unref(s, sp->u);
    free(sp);
    free(p);
}

WASI_P2_FN uint32_t wasi_p2_sock_pollable(wasi_p2_state *s, int kind, wasi_p2_tcp *t, wasi_p2_udp *u) {
    wasi_p2_pollable *p = (wasi_p2_pollable *)calloc(1, sizeof *p);
    wasi_p2_sock_poll *sp = (wasi_p2_sock_poll *)calloc(1, sizeof *sp);
    if (!p || !sp) s->trap(s, "out of memory");
    sp->kind = kind, sp->t = t, sp->u = u;
    if (t) t->refs++;
    if (u) u->refs++;
    p->ready = wasi_p2_sock_poll_ready;
    p->ctx = sp;
    return wasi_p2_table_new(s, WASI_P2_KIND_POLLABLE, p, wasi_p2_sock_poll_destroy);
}

WASI_P2_FN uint32_t wasi_sockets_tcp_tcp_socket_subscribe(wasi_p2_state *s, uint32_t self) {
    return wasi_p2_sock_pollable(s, 0, wasi_p2_tcp_get(s, self), NULL);
}

WASI_P2_FN void wasi_sockets_tcp_tcp_socket_shutdown(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t shutdown_type, uint32_t retptr) {
    wasi_p2_tcp *t = wasi_p2_tcp_get(s, self);
    int rc = WASI_P2_NOK;
    if (t->state != WASI_P2_SS_CONNECTED) {
        rc = WASI_P2_N_INVALID_STATE;
    } else {
        int how = shutdown_type == 0 ? SHUT_RD : shutdown_type == 1 ? SHUT_WR : SHUT_RDWR;
        if (shutdown(t->fd, how) < 0 && wasi_p2_errno() != ENOTCONN) rc = wasi_p2_net_errno(wasi_p2_errno());
        else {
            if (how != SHUT_WR) t->recv_shut = 1;
            if (how != SHUT_RD) t->send_shut = 1;
        }
    }
    wasi_p2_net_status(s, comp, retptr, rc);
}

/* udp-create-socket and udp */

WASI_P2_FN void wasi_sockets_udp_create_socket_create_udp_socket(wasi_p2_state *s, uint32_t comp, uint32_t address_family, uint32_t retptr) {
    int rc = WASI_P2_NOK;
    int fd = wasi_p2_net_socket((int)address_family, SOCK_DGRAM, &rc);
    if (fd < 0) {
        wasi_p2_net_fail(s, comp, retptr, retptr + 4, rc);
        return;
    }
#ifdef _WIN32
    { /* a datagram sent to a closed port would make the next receive fail with a reset; no other system does that */
#ifndef SIO_UDP_CONNRESET
#define SIO_UDP_CONNRESET _WSAIOW(IOC_VENDOR, 12)
#endif
        BOOL off = FALSE;
        DWORD ret = 0;
        WSAIoctl((SOCKET)fd, SIO_UDP_CONNRESET, &off, sizeof off, NULL, 0, &ret, NULL, NULL);
    }
#endif
    wasi_p2_udp *u = (wasi_p2_udp *)calloc(1, sizeof *u);
    if (!u) s->trap(s, "out of memory");
    u->fd = fd, u->family = (int)address_family, u->state = WASI_P2_SS_UNBOUND, u->refs = 1;
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u32(s, comp, retptr + 4, wasi_p2_table_new(s, WASI_P2_KIND_UDP_SOCKET, u, wasi_p2_udp_destroy));
}

WASI_P2_FN void wasi_sockets_udp_udp_socket_drop(wasi_p2_state *s, uint32_t h) {
    wasi_p2_udp_get(s, h);
    wasi_p2_table_drop(s, h, WASI_P2_KIND_UDP_SOCKET);
}

WASI_P2_FN int wasi_p2_udp_open(const wasi_p2_udp *u) { return u->closed ? WASI_P2_N_INVALID_STATE : WASI_P2_NOK; }

WASI_P2_FN void wasi_sockets_udp_udp_socket_start_bind(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t network, uint32_t tag, uint32_t p1, uint32_t p2,
                                                       uint32_t p3, uint32_t p4, uint32_t p5, uint32_t p6, uint32_t p7, uint32_t p8, uint32_t p9, uint32_t p10,
                                                       uint32_t p11, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_udp_get(s, self);
    wasi_p2_network_get(s, network);
    uint32_t f[11] = {p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11};
    wasi_p2_addr a = wasi_p2_addr_flat(tag, f);
    int rc = WASI_P2_NOK;
    if (u->state != WASI_P2_SS_UNBOUND) rc = WASI_P2_N_INVALID_STATE;
    if (rc == WASI_P2_NOK) rc = wasi_p2_check_bind(s, u->family, &a, WASI_P2_USE_UDP_BIND);
    if (rc == WASI_P2_NOK) {
        struct sockaddr_storage ss;
        socklen_t n = wasi_p2_to_sockaddr(&a, &ss);
        if (bind(u->fd, (struct sockaddr *)&ss, n) < 0) rc = wasi_p2_net_errno(wasi_p2_errno());
        else u->state = WASI_P2_SS_BIND_IN_PROGRESS;
    }
    wasi_p2_net_status(s, comp, retptr, rc);
}

WASI_P2_FN void wasi_sockets_udp_udp_socket_finish_bind(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_udp_get(s, self);
    int rc = WASI_P2_NOK;
    if (u->state != WASI_P2_SS_BIND_IN_PROGRESS) rc = WASI_P2_N_NOT_IN_PROGRESS;
    else u->state = WASI_P2_SS_BOUND;
    wasi_p2_net_status(s, comp, retptr, rc);
}

WASI_P2_FN void wasi_p2_dgram_destroy(wasi_p2_state *s, void *obj) { /* the handle is dropped, or the state is freed */
    wasi_p2_dgram_stream *d = (wasi_p2_dgram_stream *)obj;
    wasi_p2_udp_unref(s, d->u);
    free(d);
}

WASI_P2_FN uint32_t wasi_p2_dgram_stream_new(wasi_p2_state *s, wasi_p2_udp *u, uint32_t kind) {
    wasi_p2_dgram_stream *d = (wasi_p2_dgram_stream *)calloc(1, sizeof *d);
    if (!d) s->trap(s, "out of memory");
    d->u = u;
    u->refs++;
    return wasi_p2_table_new(s, kind, d, wasi_p2_dgram_destroy);
}

WASI_P2_FN void wasi_sockets_udp_udp_socket_stream(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t remote_tag, uint32_t tag, uint32_t p1, uint32_t p2,
                                                   uint32_t p3, uint32_t p4, uint32_t p5, uint32_t p6, uint32_t p7, uint32_t p8, uint32_t p9, uint32_t p10,
                                                   uint32_t p11, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_udp_get(s, self);
    uint32_t f[11] = {p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11};
    wasi_p2_addr a = wasi_p2_addr_flat(tag, f);
    int rc = wasi_p2_udp_open(u);
    if (rc == WASI_P2_NOK && u->state != WASI_P2_SS_BOUND) rc = WASI_P2_N_INVALID_STATE;
    if (rc == WASI_P2_NOK && remote_tag) rc = wasi_p2_check_connect(s, u->family, &a, WASI_P2_USE_UDP_CONNECT);
    if (rc != WASI_P2_NOK) {
        wasi_p2_net_fail(s, comp, retptr, retptr + 4, rc);
        return;
    }
    u->has_remote = remote_tag != 0;
    if (u->has_remote) u->remote = a;
    wasi_p2_ok(s, comp, retptr);
    /* the handles of the two streams; their kinds free them with a reference to the socket */
    uint32_t in = wasi_p2_dgram_stream_new(s, u, WASI_P2_KIND_INCOMING_DATAGRAM_STREAM);
    uint32_t out = wasi_p2_dgram_stream_new(s, u, WASI_P2_KIND_OUTGOING_DATAGRAM_STREAM);
    wasi_p2_store_u32(s, comp, retptr + 4, in);
    wasi_p2_store_u32(s, comp, retptr + 8, out);
}

WASI_P2_FN void wasi_sockets_udp_udp_socket_local_address(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_udp_get(s, self);
    wasi_p2_addr a;
    memset(&a, 0, sizeof a);
    int rc = u->state != WASI_P2_SS_BOUND || u->closed ? WASI_P2_N_INVALID_STATE : wasi_p2_name_of(u->fd, 0, &a);
    wasi_p2_address_result(s, comp, retptr, rc, &a);
}

WASI_P2_FN void wasi_sockets_udp_udp_socket_remote_address(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_udp_get(s, self);
    int rc = !u->has_remote || u->closed ? WASI_P2_N_INVALID_STATE : WASI_P2_NOK;
    wasi_p2_address_result(s, comp, retptr, rc, &u->remote);
}

WASI_P2_FN uint32_t wasi_sockets_udp_udp_socket_address_family(wasi_p2_state *s, uint32_t self) { return (uint32_t)wasi_p2_udp_get(s, self)->family; }

WASI_P2_FN void wasi_sockets_udp_udp_socket_unicast_hop_limit(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_udp_get(s, self);
    int v = 0, rc = wasi_p2_udp_open(u);
    if (rc == WASI_P2_NOK) rc = wasi_p2_hop_get(u->fd, u->family, &v);
    wasi_p2_number_result(s, comp, retptr, 1, 1, rc, (uint64_t)v);
}
WASI_P2_FN void wasi_sockets_udp_udp_socket_set_unicast_hop_limit(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t value, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_udp_get(s, self);
    int rc = wasi_p2_udp_open(u);
    if (rc == WASI_P2_NOK) rc = wasi_p2_hop_set(u->fd, u->family, value);
    wasi_p2_net_status(s, comp, retptr, rc);
}
WASI_P2_FN void wasi_sockets_udp_udp_socket_receive_buffer_size(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_udp_get(s, self);
    int v = 0, rc = wasi_p2_udp_open(u);
    if (rc == WASI_P2_NOK) rc = wasi_p2_getopt(u->fd, SOL_SOCKET, SO_RCVBUF, &v);
    wasi_p2_number_result(s, comp, retptr, 8, 8, rc, (uint64_t)v);
}
WASI_P2_FN void wasi_sockets_udp_udp_socket_set_receive_buffer_size(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t value, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_udp_get(s, self);
    int rc = wasi_p2_udp_open(u);
    if (rc == WASI_P2_NOK) rc = wasi_p2_buffer_set(u->fd, SO_RCVBUF, value);
    wasi_p2_net_status(s, comp, retptr, rc);
}
WASI_P2_FN void wasi_sockets_udp_udp_socket_send_buffer_size(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_udp_get(s, self);
    int v = 0, rc = wasi_p2_udp_open(u);
    if (rc == WASI_P2_NOK) rc = wasi_p2_getopt(u->fd, SOL_SOCKET, SO_SNDBUF, &v);
    wasi_p2_number_result(s, comp, retptr, 8, 8, rc, (uint64_t)v);
}
WASI_P2_FN void wasi_sockets_udp_udp_socket_set_send_buffer_size(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t value, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_udp_get(s, self);
    int rc = wasi_p2_udp_open(u);
    if (rc == WASI_P2_NOK) rc = wasi_p2_buffer_set(u->fd, SO_SNDBUF, value);
    wasi_p2_net_status(s, comp, retptr, rc);
}

WASI_P2_FN uint32_t wasi_sockets_udp_udp_socket_subscribe(wasi_p2_state *s, uint32_t self) {
    return wasi_p2_sock_pollable(s, 3, NULL, wasi_p2_udp_get(s, self));
}

WASI_P2_FN wasi_p2_dgram_stream *wasi_p2_incoming_get(wasi_p2_state *s, uint32_t h) {
    return (wasi_p2_dgram_stream *)wasi_p2_table_get(s, h, WASI_P2_KIND_INCOMING_DATAGRAM_STREAM)->obj;
}
WASI_P2_FN wasi_p2_dgram_stream *wasi_p2_outgoing_get(wasi_p2_state *s, uint32_t h) {
    return (wasi_p2_dgram_stream *)wasi_p2_table_get(s, h, WASI_P2_KIND_OUTGOING_DATAGRAM_STREAM)->obj;
}

WASI_P2_FN void wasi_sockets_udp_incoming_datagram_stream_drop(wasi_p2_state *s, uint32_t h) {
    wasi_p2_incoming_get(s, h);
    wasi_p2_table_drop(s, h, WASI_P2_KIND_INCOMING_DATAGRAM_STREAM);
}
WASI_P2_FN void wasi_sockets_udp_outgoing_datagram_stream_drop(wasi_p2_state *s, uint32_t h) {
    wasi_p2_outgoing_get(s, h);
    wasi_p2_table_drop(s, h, WASI_P2_KIND_OUTGOING_DATAGRAM_STREAM);
}

typedef struct {
    uint8_t *data;
    uint32_t len;
    wasi_p2_addr src;
} wasi_p2_received;

WASI_P2_FN void wasi_sockets_udp_incoming_datagram_stream_receive(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t max_results, uint32_t retptr) {
    wasi_p2_udp *u = wasi_p2_incoming_get(s, self)->u;
    int rc = wasi_p2_udp_open(u);
    uint32_t count = 0, capacity = 0;
    wasi_p2_received *got = NULL;
    uint8_t *buf = (uint8_t *)malloc(65536); /* scratch only: filled and copied out before the call returns */
    if (!buf) s->trap(s, "out of memory");
    while (rc == WASI_P2_NOK && count < max_results) {
        struct sockaddr_storage ss;
        socklen_t n = sizeof ss;
        ssize_t r = WASI_P2_RECVFROM(u->fd, buf, sizeof buf, 0, (struct sockaddr *)&ss, &n);
        if (r < 0) {
            if (wasi_p2_errno() == EAGAIN || wasi_p2_errno() == EWOULDBLOCK) break;
            if (count) break;
            rc = wasi_p2_net_errno(wasi_p2_errno());
            break;
        }
        wasi_p2_addr src = wasi_p2_from_sockaddr(&ss);
        if (u->has_remote && (src.family != u->remote.family || src.port != u->remote.port || memcmp(src.v4, u->remote.v4, 4) || memcmp(src.v6, u->remote.v6, 16)))
            continue; /* a datagram from another address than the one the stream is for */
        if (count == capacity) {
            capacity = capacity ? capacity * 2 : 4;
            got = (wasi_p2_received *)realloc(got, capacity * sizeof *got);
            if (!got) s->trap(s, "out of memory");
        }
        got[count].data = (uint8_t *)malloc(r ? (size_t)r : 1);
        if (!got[count].data) s->trap(s, "out of memory");
        memcpy(got[count].data, buf, (size_t)r);
        got[count].len = (uint32_t)r;
        got[count].src = src;
        count++;
    }
    free(buf);
    if (rc != WASI_P2_NOK) {
        for (uint32_t i = 0; i < count; i++) free(got[i].data);
        free(got);
        wasi_p2_net_fail(s, comp, retptr, retptr + 4, rc);
        return;
    }
    uint32_t ptr = wasi_p2_alloc(s, comp, 4, 40 * count);
    for (uint32_t i = 0; i < count; i++) {
        uint32_t dptr = wasi_p2_alloc(s, comp, 1, got[i].len);
        if (got[i].len) memcpy(wasi_p2_mem(s, comp, dptr, got[i].len), got[i].data, got[i].len);
        free(got[i].data);
        wasi_p2_store_u32(s, comp, ptr + 40 * i, dptr);
        wasi_p2_store_u32(s, comp, ptr + 40 * i + 4, got[i].len);
        wasi_p2_write_addr(s, comp, ptr + 40 * i + 8, &got[i].src);
    }
    free(got);
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u32(s, comp, retptr + 4, ptr);
    wasi_p2_store_u32(s, comp, retptr + 8, count);
}

WASI_P2_FN uint32_t wasi_sockets_udp_incoming_datagram_stream_subscribe(wasi_p2_state *s, uint32_t self) {
    return wasi_p2_sock_pollable(s, 1, NULL, wasi_p2_incoming_get(s, self)->u);
}

WASI_P2_FN void wasi_sockets_udp_outgoing_datagram_stream_check_send(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_dgram_stream *o = wasi_p2_outgoing_get(s, self);
    int rc = wasi_p2_udp_open(o->u);
    if (rc != WASI_P2_NOK) {
        wasi_p2_net_fail(s, comp, retptr, retptr + 8, rc);
        return;
    }
    o->permit = WASI_P2_CHECK_SEND_PERMIT;
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u64(s, comp, retptr + 8, WASI_P2_CHECK_SEND_PERMIT);
}

WASI_P2_FN void wasi_sockets_udp_outgoing_datagram_stream_send(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t ptr, uint32_t length, uint32_t retptr) {
    wasi_p2_dgram_stream *o = wasi_p2_outgoing_get(s, self);
    wasi_p2_udp *u = o->u;
    if (length > o->permit) s->trap(s, "send of more datagrams than check-send permitted");
    o->permit = 0;
    uint64_t sent = 0;
    int rc = wasi_p2_udp_open(u);
    for (uint32_t i = 0; rc == WASI_P2_NOK && i < length; i++) {
        uint32_t base = ptr + 44 * i;
        uint32_t dptr = wasi_p2_load_u32(s, comp, base), dlen = wasi_p2_load_u32(s, comp, base + 4);
        const uint8_t *data = wasi_p2_mem(s, comp, dptr, dlen);
        int has_remote = wasi_p2_load_u8(s, comp, base + 8) != 0;
        wasi_p2_addr target;
        int e = WASI_P2_NOK, would_block = 0;
        if (u->has_remote) {
            if (has_remote) { /* the stream has its peer: the datagram names none, or exactly that one */
                wasi_p2_addr named = wasi_p2_read_addr(s, comp, base + 12);
                if (named.family != u->remote.family || named.port != u->remote.port || memcmp(named.v4, u->remote.v4, 4) || memcmp(named.v6, u->remote.v6, 16) ||
                    named.flow != u->remote.flow || named.scope != u->remote.scope)
                    e = WASI_P2_N_INVALID_ARGUMENT;
            }
            target = u->remote;
        } else if (!has_remote) {
            e = WASI_P2_N_INVALID_ARGUMENT;
            memset(&target, 0, sizeof target);
        } else {
            target = wasi_p2_read_addr(s, comp, base + 12);
            e = wasi_p2_check_connect(s, u->family, &target, WASI_P2_USE_UDP_OUTGOING);
        }
        if (e == WASI_P2_NOK) {
            struct sockaddr_storage ss;
            socklen_t n = wasi_p2_to_sockaddr(&target, &ss);
            if (WASI_P2_SENDTO(u->fd, data, dlen, MSG_NOSIGNAL, (struct sockaddr *)&ss, n) < 0) {
                if (wasi_p2_errno() == EAGAIN || wasi_p2_errno() == EWOULDBLOCK) would_block = 1;
                else e = wasi_p2_net_errno(wasi_p2_errno());
            }
        }
        if (would_block) break; /* the system cannot take it now: the rest is not sent */
        if (e != WASI_P2_NOK) {
            if (!sent) rc = e; /* an error after something was sent is not reported */
            break;
        }
        sent++;
    }
    if (rc != WASI_P2_NOK) {
        wasi_p2_net_fail(s, comp, retptr, retptr + 8, rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u64(s, comp, retptr + 8, sent);
}

WASI_P2_FN uint32_t wasi_sockets_udp_outgoing_datagram_stream_subscribe(wasi_p2_state *s, uint32_t self) {
    return wasi_p2_sock_pollable(s, 2, NULL, wasi_p2_outgoing_get(s, self)->u);
}

/* ip-name-lookup */

WASI_P2_FN void wasi_p2_resolved_destroy(wasi_p2_state *s, void *obj) {
    wasi_p2_resolved *r = (wasi_p2_resolved *)obj;
    (void)s;
    free(r->list);
    free(r);
}

WASI_P2_FN int wasi_p2_name_chars(const char *name) {
    for (const char *c = name; *c; c++)
        if (!((*c >= 'a' && *c <= 'z') || (*c >= 'A' && *c <= 'Z') || (*c >= '0' && *c <= '9') || *c == '.' || *c == '-' || *c == '_')) return 0;
    return 1;
}

WASI_P2_FN int wasi_p2_same_addr(const wasi_p2_addr *a, const wasi_p2_addr *b) {
    return a->family == b->family && !memcmp(a->v4, b->v4, 4) && !memcmp(a->v6, b->v6, 16);
}

WASI_P2_FN void wasi_sockets_ip_name_lookup_resolve_addresses(wasi_p2_state *s, uint32_t comp, uint32_t network, uint32_t ptr, uint32_t length,
                                                              uint32_t retptr) {
    wasi_p2_network_get(s, network);
    const uint8_t *raw = wasi_p2_mem(s, comp, ptr, length);
    int rc = WASI_P2_NOK;
    wasi_p2_resolved *r = NULL;
    char *name = (char *)malloc((size_t)length + 1);
    if (!name) s->trap(s, "out of memory");
    memcpy(name, raw, length);
    name[length] = '\0';
    if (!s->allow_ip_name_lookup) {
        rc = WASI_P2_N_ACCESS_DENIED;
    } else if (length == 0 || memchr(raw, 0, length) || strchr(name, '%')) {
        rc = WASI_P2_N_INVALID_ARGUMENT;
    } else {
        for (uint32_t i = 0; i < length; i++)
            if (raw[i] >= 0x80) rc = WASI_P2_N_INVALID_ARGUMENT;
    }
    if (rc == WASI_P2_NOK) {
        r = (wasi_p2_resolved *)calloc(1, sizeof *r);
        if (!r) s->trap(s, "out of memory");
        struct in_addr a4;
        struct in6_addr a6;
        r->list = (wasi_p2_addr *)calloc(1, sizeof *r->list);
        if (!r->list) s->trap(s, "out of memory");
        if (inet_pton(AF_INET, name, &a4) == 1) {
            r->list[0].family = 0;
            memcpy(r->list[0].v4, &a4, 4);
            r->count = 1;
        } else if (inet_pton(AF_INET6, name, &a6) == 1) {
            r->list[0].family = 1;
            for (int i = 0; i < 8; i++) r->list[0].v6[i] = (uint16_t)(a6.s6_addr[2 * i] << 8 | a6.s6_addr[2 * i + 1]);
            r->count = 1;
        } else if (!wasi_p2_name_chars(name)) {
            rc = WASI_P2_N_INVALID_ARGUMENT;
        } else {
            struct addrinfo hints, *res = NULL, *p;
            memset(&hints, 0, sizeof hints);
            hints.ai_family = AF_UNSPEC;
            hints.ai_socktype = SOCK_STREAM;
            wasi_p2_net_start();
            int g = getaddrinfo(name, NULL, &hints, &res);
            if (g != 0) {
                rc = g == EAI_AGAIN ? WASI_P2_N_TEMPORARY_RESOLVER_FAILURE : g == EAI_FAIL ? WASI_P2_N_PERMANENT_RESOLVER_FAILURE : WASI_P2_N_NAME_UNRESOLVABLE;
            } else {
                uint32_t cap = 1;
                for (p = res; p; p = p->ai_next) {
                    if (p->ai_family != AF_INET && p->ai_family != AF_INET6) continue;
                    wasi_p2_addr a = wasi_p2_from_sockaddr((struct sockaddr_storage *)p->ai_addr);
                    int dup = 0;
                    for (uint32_t i = 0; i < r->count; i++)
                        if (wasi_p2_same_addr(&r->list[i], &a)) dup = 1;
                    if (dup) continue;
                    if (r->count == cap) {
                        cap *= 2;
                        r->list = (wasi_p2_addr *)realloc(r->list, cap * sizeof *r->list);
                        if (!r->list) s->trap(s, "out of memory");
                    }
                    r->list[r->count++] = a;
                }
                freeaddrinfo(res);
            }
        }
    }
    free(name);
    if (rc != WASI_P2_NOK) {
        if (r) wasi_p2_resolved_destroy(s, r);
        wasi_p2_net_fail(s, comp, retptr, retptr + 4, rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u32(s, comp, retptr + 4, wasi_p2_table_new(s, WASI_P2_KIND_RESOLVE_STREAM, r, wasi_p2_resolved_destroy));
}

WASI_P2_FN void wasi_sockets_ip_name_lookup_resolve_address_stream_resolve_next_address(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_resolved *r = (wasi_p2_resolved *)wasi_p2_table_get(s, self, WASI_P2_KIND_RESOLVE_STREAM)->obj;
    wasi_p2_ok(s, comp, retptr);
    if (r->pos >= r->count) {
        wasi_p2_store_u8(s, comp, retptr + 2, 0);
        return;
    }
    const wasi_p2_addr *a = &r->list[r->pos++];
    wasi_p2_store_u8(s, comp, retptr + 2, 1);
    wasi_p2_store_u8(s, comp, retptr + 4, (uint8_t)a->family);
    if (a->family == 0) memcpy(wasi_p2_mem(s, comp, retptr + 6, 4), a->v4, 4);
    else
        for (int i = 0; i < 8; i++) wasi_p2_store_u16(s, comp, retptr + 6 + 2 * i, a->v6[i]);
}

WASI_P2_FN uint32_t wasi_sockets_ip_name_lookup_resolve_address_stream_subscribe(wasi_p2_state *s, uint32_t self) {
    wasi_p2_table_get(s, self, WASI_P2_KIND_RESOLVE_STREAM);
    return wasi_p2_sock_pollable(s, 4, NULL, NULL);
}

WASI_P2_FN void wasi_sockets_ip_name_lookup_resolve_address_stream_drop(wasi_p2_state *s, uint32_t h) {
    wasi_p2_table_get(s, h, WASI_P2_KIND_RESOLVE_STREAM);
    wasi_p2_table_drop(s, h, WASI_P2_KIND_RESOLVE_STREAM);
}

#endif /* WASI_P2_SOCKETS_H */
