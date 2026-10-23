/* The system calls of sockets as they are on POSIX and on Windows (Winsock), for wasi_p2_sockets.h and wasi_p2_http.h. */
#ifndef WASI_P2_NET_H
#define WASI_P2_NET_H

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

#include "wasi_p2_io.h" /* WASI_P2_FN */

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
WASI_P2_FN int wasi_p2_set_blocking(int fd, int blocking) {
#ifdef _WIN32
    u_long on = blocking ? 0 : 1;
    return ioctlsocket((SOCKET)fd, FIONBIO, &on) == 0 ? 0 : -1;
#else
    int fl = fcntl(fd, F_GETFL, 0);
    if (fl < 0) return -1;
    return fcntl(fd, F_SETFL, blocking ? (fl & ~O_NONBLOCK) : (fl | O_NONBLOCK)) < 0 ? -1 : 0;
#endif
}

#endif /* WASI_P2_NET_H */
