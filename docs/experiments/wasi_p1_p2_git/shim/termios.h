/* wasi-libc has no termios.h; there is no terminal. */
#ifndef SHIM_TERMIOS_H
#define SHIM_TERMIOS_H
#include <sys/types.h>
typedef unsigned int tcflag_t; typedef unsigned char cc_t; typedef unsigned int speed_t;
struct termios { tcflag_t c_iflag, c_oflag, c_cflag, c_lflag; cc_t c_cc[32]; };
#define ECHO 8
#define ICANON 2
#define TCSAFLUSH 2
#define TCSANOW 0
#define VMIN 6
#define VTIME 5
int tcgetattr(int, struct termios *); int tcsetattr(int, int, const struct termios *); pid_t tcgetpgrp(int);
#endif
