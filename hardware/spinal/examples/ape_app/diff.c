/* Original bounded line diff. All tokenization, comparison, DP and edit-script
 * construction run on APE. No host callbacks, libc, heap or ISA intrinsics. */
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define LIMIT 32
#define NOINLINE __attribute__((noinline))
struct Input { u64 old_bytes, new_bytes; u8 old_text[512], new_text[512]; };
struct Edit { u32 kind, old_line, new_line; }; /* keep=0, delete=1, insert=2 */
struct Output { u32 status, count, cost, old_lines, new_lines; struct Edit edits[64]; };
struct Line { const u8 *text; u32 size; };
static struct Line old_lines[LIMIT], new_lines[LIMIT];
static u16 lcs[LIMIT + 1][LIMIT + 1];
static volatile u64 initial_cookie = 0x48415453;
static const volatile u8 signature[] = "HATS";
static volatile u64 zero_cookie;

NOINLINE u64 ape_abi_sum(u64 a, u64 b, u64 c, u64 d, u64 e,
                        u64 f, u64 g, u64 h, u64 i) {
    return a + b + c + d + e + f + g + h + i;
}

/* Newline is part of a line: CRLF and absent final LF are byte-exact. */
static NOINLINE int split(const u8 *s, u64 size, struct Line *lines) {
    u32 count = 0, begin = 0;
    for (u32 pos = 0; pos < size; ++pos) {
        if (s[pos] == '\n' || pos + 1 == size) {
            if (count == LIMIT) return -1;
            lines[count].text = s + begin;
            lines[count].size = pos + 1 - begin;
            ++count;
            begin = pos + 1;
        }
    }
    return (int)count;
}

static NOINLINE int equal(const struct Line *a, const struct Line *b) {
    if (a->size != b->size) return 0;
    for (u32 i = 0; i < a->size; ++i)
        if (a->text[i] != b->text[i]) return 0;
    return 1;
}

u64 ape_main(const struct Input *input) {
    volatile struct Output *out = (volatile struct Output *)0x18000;
    out->status = 255;
    out->count = out->cost = out->old_lines = out->new_lines = 0;
    if (initial_cookie != 0x48415453 || signature[0] != 'H' || zero_cookie != 0) {
        out->status = 224;
        return 224;
    }
    zero_cookie = 1; /* A relaunch must clear .bss again. */
    if (input->old_bytes > 512 || input->new_bytes > 512) {
        out->status = 1;
        return 1;
    }
    int n = split(input->old_text, input->old_bytes, old_lines);
    int m = split(input->new_text, input->new_bytes, new_lines);
    if (n < 0 || m < 0) { out->status = 2; return 2; }
    out->old_lines = (u32)n;
    out->new_lines = (u32)m;
    /* Boundary cells are zero from runtime .bss initialization. */
    for (int i = n - 1; i >= 0; --i) {
        for (int j = m - 1; j >= 0; --j) {
            if (equal(&old_lines[i], &new_lines[j])) lcs[i][j] = lcs[i+1][j+1] + 1;
            else lcs[i][j] = lcs[i+1][j] >= lcs[i][j+1] ? lcs[i+1][j] : lcs[i][j+1];
        }
    }
    u32 i = 0, j = 0, count = 0, cost = 0;
    while (i < (u32)n || j < (u32)m) {
        u32 kind;
        if (i < (u32)n && j < (u32)m && equal(&old_lines[i], &new_lines[j])) kind = 0;
        else if (i < (u32)n && (j == (u32)m || lcs[i+1][j] >= lcs[i][j+1])) kind = 1;
        else kind = 2;
        out->edits[count].kind = kind;
        out->edits[count].old_line = i;
        out->edits[count].new_line = j;
        ++count;
        if (kind != 2) ++i;
        if (kind != 1) ++j;
        if (kind != 0) ++cost;
    }
    out->count = count;
    out->cost = cost;
    out->status = 0;
    return 0;
}
