/* lg2.c registers a TLS stream made by the host bridge; with libgit2's own sockets there is none (HTTPS needs a TLS library or a host interface). */
#include <git2/sys/stream.h>
int lg2_stream_new(git_stream **out, const char *host, const char *port, int tls) { (void)out; (void)host; (void)port; (void)tls; return -1; }
