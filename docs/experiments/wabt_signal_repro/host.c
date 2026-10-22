#include <stdio.h>
#include <string.h>
void a_setup(void); int a_oob(void);
void b_setup(void); int b_oob(void);
int main(int argc, char **argv) {
    a_setup();
    b_setup();   /* b was set up last: the handler of SIGSEGV is now the one of b's copy of the runtime */
    int use_b = argc > 1 && !strcmp(argv[1], "b");
    printf("calling %s_oob() ...\n", use_b ? "b" : "a");
    fflush(stdout);
    int returned = use_b ? b_oob() : a_oob();
    printf("%s_oob() %s\n", use_b ? "b" : "a", returned ? "returned" : "trapped (as it should)");
    return 0;
}
