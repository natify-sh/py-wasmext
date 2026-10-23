/* Prints, for each errno given as a number on the command line, the errno of WASI that wasi_core.h makes of it. */
#include <stdio.h>
#include <stdlib.h>

#include "wasi_core.h"

int main(int argc, char **argv) {
    for (int i = 1; i < argc; i++) printf("%d %u\n", atoi(argv[i]), (unsigned)wasi_errno(atoi(argv[i])));
    return 0;
}
