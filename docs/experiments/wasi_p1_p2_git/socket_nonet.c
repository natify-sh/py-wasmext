/* wasip2 build: no host network functions are imported; every connection fails (local git operations only). */
/*
 * WASI preview1 has no sockets, so this replaces libgit2's socket stream: a connection is a handle the host gives, and
 * the module reads and writes it through four functions it imports from `wasmhost_net`. The host does the TCP and, for
 * a stream made with `tls`, the TLS and the check of the certificate. libgit2's own HTTP client runs on top.
 */
#include "streams/socket.h"

#include <git2/sys/errors.h>
#include <git2/sys/stream.h>

#include <stdlib.h>
#include <string.h>


static int host_connect(const char *h, int hl, const char *p, int pl, int tls) { (void)h;(void)hl;(void)p;(void)pl;(void)tls; return -1; }
static int host_read(int h, void *b, int n) { (void)h;(void)b;(void)n; return -1; }
static int host_write(int h, const void *b, int n) { (void)h;(void)b;(void)n; return -1; }
static int host_close(int h) { (void)h; return 0; }

/* ---- the stream ---- */

typedef struct {
	git_stream parent;
	char *host;
	char *port;
	int handle;
} host_stream;

static int hs_connect(git_stream *s)
{
	host_stream *hs = (host_stream *)s;
	int h = host_connect(hs->host, (int)strlen(hs->host), hs->port, (int)strlen(hs->port), s->encrypted);
	if (h < 0) {
		git_error_set_str(GIT_ERROR_NET, "the host could not connect");
		return -1;
	}
	hs->handle = h;
	return 0;
}

/* The host verifies the certificate; libgit2 is not shown it. */
static int hs_certificate(git_cert **out, git_stream *s)
{
	(void)out; (void)s;
	git_error_set_str(GIT_ERROR_NET, "the certificate is checked by the host");
	return -1;
}

static int hs_set_proxy(git_stream *s, const git_proxy_options *o)
{
	(void)s; (void)o;
	return 0;
}

static ssize_t hs_read(git_stream *s, void *data, size_t len)
{
	int n = host_read(((host_stream *)s)->handle, data, (int)len);
	if (n < 0) {
		git_error_set_str(GIT_ERROR_NET, "the host failed to read");
		return -1;
	}
	return n;
}

static ssize_t hs_write(git_stream *s, const char *data, size_t len, int flags)
{
	size_t done = 0;
	(void)flags;
	while (done < len) {
		int n = host_write(((host_stream *)s)->handle, data + done, (int)(len - done));
		if (n <= 0) {
			git_error_set_str(GIT_ERROR_NET, "the host failed to write");
			return -1;
		}
		done += (size_t)n;
	}
	return (ssize_t)done;
}

static int hs_close(git_stream *s)
{
	host_stream *hs = (host_stream *)s;
	if (hs->handle >= 0)
		host_close(hs->handle);
	hs->handle = -1;
	return 0;
}

static void hs_free(git_stream *s)
{
	host_stream *hs = (host_stream *)s;
	free(hs->host);
	free(hs->port);
	free(hs);
}

int lg2_stream_new(git_stream **out, const char *host, const char *port, int tls)
{
	host_stream *hs = calloc(1, sizeof(*hs));
	if (!hs)
		return -1;
	hs->parent.version = GIT_STREAM_VERSION;
	hs->parent.encrypted = tls;
	hs->parent.connect = hs_connect;
	hs->parent.certificate = hs_certificate;
	hs->parent.set_proxy = hs_set_proxy;
	hs->parent.read = hs_read;
	hs->parent.write = hs_write;
	hs->parent.close = hs_close;
	hs->parent.free = hs_free;
	hs->host = strdup(host);
	hs->port = strdup(port ? port : (tls ? "443" : "80"));
	hs->handle = -1;
	*out = &hs->parent;
	return 0;
}

int git_socket_stream__connect_timeout = 0;
int git_socket_stream__timeout = 0;

int git_socket_stream_new(git_stream **out, const char *host, const char *port)
{
	return lg2_stream_new(out, host, port, 0);
}

int git_socket_stream_global_init(void) { return 0; }
