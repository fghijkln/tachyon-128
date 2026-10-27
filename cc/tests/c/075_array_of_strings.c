#include <stdio.h>
#include <string.h>
const char *months[] = {"January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"};
char grid[3][6] = {"abcde", "fghij", "klmno"};
int main(void) {
    int longest = 0; const char *lw = 0;
    for (int i = 0; i < 12; i++) if ((int)strlen(months[i]) > longest) { longest = strlen(months[i]); lw = months[i]; }
    printf("%s %d\n", lw, longest);
    for (int i = 0; i < 3; i++) printf("%c", grid[i][i]); printf("\n");
    for (int j = 0; j < 5; j++) printf("%c", grid[2 - j % 3][j]); printf("\n");
    char *w[3]; char storage[3][10]; for (int i = 0; i < 3; i++) { w[i] = storage[i]; sprintf(w[i], "w%d", i * 11); }
    printf("%s %s %s\n", w[0], w[1], w[2]);
    printf("%c\n", months[11][2]);
    return 0;
}
