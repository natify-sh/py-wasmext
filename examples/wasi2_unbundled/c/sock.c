#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#ifndef PORT
#define PORT 47123
#endif

int main(void) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 2; }
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons(PORT);
    a.sin_addr.s_addr = htonl(0x7f000001);
    if (connect(fd, (struct sockaddr *)&a, sizeof a) < 0) { perror("connect"); return 3; }
    if (send(fd, "ping", 4, 0) != 4) { perror("send"); return 4; }
    char buf[64];
    ssize_t n = recv(fd, buf, sizeof buf - 1, 0);
    if (n < 0) { perror("recv"); return 5; }
    buf[n] = 0;
    printf("reply: %s\n", buf);
    close(fd);
    return 0;
}
