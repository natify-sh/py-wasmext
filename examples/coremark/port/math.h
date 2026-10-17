/* barebones/cvt.c needs modf; wasm32-freestanding has no libc, so there is no <math.h>: this is the one function. */
#ifndef PORT_MATH_H
#define PORT_MATH_H
double modf(double x, double *integral);
#endif
