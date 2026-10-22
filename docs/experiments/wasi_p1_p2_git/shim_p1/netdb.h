/* wasip1 only: wasi-libc of preview1 has no netdb.h (no name lookup). Declarations for what git compiles against; extra_p1.c makes every lookup fail. */
#ifndef SHIM_NETDB_H
#define SHIM_NETDB_H
#include <sys/socket.h>
#include <netinet/in.h>
struct addrinfo { int ai_flags, ai_family, ai_socktype, ai_protocol; socklen_t ai_addrlen; struct sockaddr *ai_addr; char *ai_canonname; struct addrinfo *ai_next; };
struct hostent { char *h_name; char **h_aliases; int h_addrtype, h_length; char **h_addr_list; };
#define AI_PASSIVE 1
#define AI_CANONNAME 2
#define AI_NUMERICHOST 4
#define AI_ADDRCONFIG 0x20
#define NI_NUMERICHOST 1
#define NI_NUMERICSERV 2
#define NI_MAXHOST 1025
#define NI_MAXSERV 32
#define EAI_FAIL (-4)
#define EAI_NONAME (-2)
int getaddrinfo(const char *, const char *, const struct addrinfo *, struct addrinfo **);
void freeaddrinfo(struct addrinfo *);
const char *gai_strerror(int);
int getnameinfo(const struct sockaddr *, socklen_t, char *, socklen_t, char *, socklen_t, int);
struct hostent *gethostbyname(const char *);
#endif
