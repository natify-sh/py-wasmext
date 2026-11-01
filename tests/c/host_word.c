/* Prints the host layout word of the artifact `ARTIFACT_NAME` (tests/test_artifacts.py). */
#include <stdio.h>
#include "artifact.h"

#define CAT_(a, b) a##b
#define CAT(a, b) CAT_(a, b)
extern const artifact_api *CAT(artifact_, ARTIFACT_NAME)(void);

int main(void) {
    printf("%u\n", (unsigned)CAT(artifact_, ARTIFACT_NAME)()->host_layout);
    return 0;
}
