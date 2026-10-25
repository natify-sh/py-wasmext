#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static int fail(const char *what) { perror(what); return 1; }

int main(void) {
    /* TCP: a server and a client in one program */
    int srv = socket(AF_INET, SOCK_STREAM, 0);
    if (srv < 0) return fail("socket");
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(0x7f000001);
    if (bind(srv, (struct sockaddr *)&a, sizeof a) < 0) return fail("bind");
    if (listen(srv, 4) < 0) return fail("listen");
    socklen_t len = sizeof a;
    if (getsockname(srv, (struct sockaddr *)&a, &len) < 0) return fail("getsockname");
    printf("tcp port>0=%d\n", ntohs(a.sin_port) > 0);
    int cli = socket(AF_INET, SOCK_STREAM, 0);
    if (connect(cli, (struct sockaddr *)&a, sizeof a) < 0) return fail("connect");
    int conn = accept(srv, NULL, NULL);
    if (conn < 0) return fail("accept");
    if (send(cli, "ping", 4, 0) != 4) return fail("send");
    char buf[16] = {0};
    if (recv(conn, buf, sizeof buf, 0) != 4) return fail("recv");
    printf("server got %s\n", buf);
    if (send(conn, "pong", 4, 0) != 4) return fail("send2");
    memset(buf, 0, sizeof buf);
    if (recv(cli, buf, sizeof buf, 0) != 4) return fail("recv2");
    printf("client got %s\n", buf);
    close(cli); close(conn); close(srv);

    /* UDP: two sockets on the loopback */
    int u1 = socket(AF_INET, SOCK_DGRAM, 0), u2 = socket(AF_INET, SOCK_DGRAM, 0);
    if (u1 < 0 || u2 < 0) return fail("udp socket");
    struct sockaddr_in b;
    memset(&b, 0, sizeof b);
    b.sin_family = AF_INET;
    b.sin_addr.s_addr = htonl(0x7f000001);
    if (bind(u1, (struct sockaddr *)&b, sizeof b) < 0) return fail("udp bind");
    len = sizeof b;
    if (getsockname(u1, (struct sockaddr *)&b, &len) < 0) return fail("udp getsockname");
    if (sendto(u2, "dgram", 5, 0, (struct sockaddr *)&b, sizeof b) != 5) return fail("sendto");
    memset(buf, 0, sizeof buf);
    struct sockaddr_in from;
    socklen_t flen = sizeof from;
    if (recvfrom(u1, buf, sizeof buf, 0, (struct sockaddr *)&from, &flen) != 5) return fail("recvfrom");
    printf("udp got %s\n", buf);
    close(u1); close(u2);

    /* name lookup */
    struct addrinfo hints, *res = NULL;
    memset(&hints, 0, sizeof hints);
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    int rc = getaddrinfo("localhost", "80", &hints, &res);
    if (rc != 0) { printf("getaddrinfo: %s\n", gai_strerror(rc)); return 2; }
    char ip[64];
    inet_ntop(AF_INET, &((struct sockaddr_in *)res->ai_addr)->sin_addr, ip, sizeof ip);
    printf("localhost=%s\n", ip);
    freeaddrinfo(res);
    return 0;
}
