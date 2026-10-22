/* wasi-libc has no pwd.h; libgit2 asks for the home directory of a user. compat.c answers "not found". */
#ifndef SHIM_PWD_H
#define SHIM_PWD_H
#include <sys/types.h>
#include <stddef.h>
struct passwd { char *pw_name; char *pw_passwd; uid_t pw_uid; gid_t pw_gid; char *pw_gecos; char *pw_dir; char *pw_shell; };
int getpwuid_r(uid_t uid, struct passwd *pwd, char *buf, size_t buflen, struct passwd **result);
struct passwd *getpwuid(uid_t); struct passwd *getpwnam(const char *);
#endif
