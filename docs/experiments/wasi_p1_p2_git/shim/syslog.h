/* wasi-libc has no syslog.h; git only logs to syslog from its daemon. */
#ifndef SHIM_SYSLOG_H
#define SHIM_SYSLOG_H
#define LOG_EMERG 0
#define LOG_ALERT 1
#define LOG_CRIT 2
#define LOG_ERR 3
#define LOG_WARNING 4
#define LOG_NOTICE 5
#define LOG_INFO 6
#define LOG_DEBUG 7
#define LOG_PID 1
#define LOG_DAEMON (3<<3)
static inline void openlog(const char *i, int o, int f) { (void)i; (void)o; (void)f; }
static inline void syslog(int p, const char *f, ...) { (void)p; (void)f; }
static inline void closelog(void) {}
#endif
