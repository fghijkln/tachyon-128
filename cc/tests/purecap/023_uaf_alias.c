/* use after free through an alias: the program keeps a second copy of the pointer inside another heap
   object (a cache entry) and frees the block through the first one. Revocation is a property of the
   allocation, not of one pointer: the alias, loaded back from memory, still carries its tag but its base
   is now in the revocation bitmap, so the access traps (cause 10) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct entry { char *name; int hits; };

int main(void) {
    char *name = malloc(16);
    strcpy(name, "alice");
    struct entry *cache = malloc(sizeof *cache);
    cache->name = name;                   /* alias stored in memory */
    cache->hits = 1;
    printf("cached %s (%d)\n", cache->name, cache->hits);
    free(name);                           /* freed through the original pointer */
    char *alias = cache->name;
    printf("alias tag %d\n", (int)__builtin_cheri_tag_get(alias));
    alias[0] = 'm';                       /* traps here */
    printf("not reached\n");
    return 0;
}
