/* stale pointer after realloc: growing a buffer moves it and frees the old block, so a pointer that
   still refers to the old buffer traps (cause 10) instead of reading or writing freed memory */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    char *buf = malloc(8);
    strcpy(buf, "abc");
    char *old = buf;
    buf = realloc(buf, 4096);
    strcat(buf, "def");
    printf("buf = %s, moved: %s\n", buf, buf != old ? "yes" : "no");
    printf("old[0] = %c\n", old[0]);      /* traps here */
    printf("not reached\n");
    return 0;
}
