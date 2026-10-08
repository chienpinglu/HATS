/* Original adapter. Parsing and incremental reuse execute unmodified upstream C. */
#include "profile.h"
#include <tree_sitter/api.h>
#include <assert.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_INPUT (4u * 1024u * 1024u)
#define CHUNK 256u
typedef struct {
  char *bytes;
  uint32_t size, last;
  uint64_t calls, delivered, unique, backward;
  unsigned char seen[MAX_INPUT / CHUNK];
} Input;
const TSLanguage *tree_sitter_json(void);

static void load(Input *in, const char *path) {
  FILE *f = fopen(path, "rb");
  if (!f || fseek(f, 0, SEEK_END)) abort();
  long length = ftell(f);
  if (length < 0 || (unsigned long)length > MAX_INPUT || fseek(f, 0, SEEK_SET)) abort();
  in->size = (uint32_t)length;
  in->bytes = malloc(in->size + 1);
  if (!in->bytes || fread(in->bytes, 1, in->size, f) != in->size || fclose(f)) abort();
  in->bytes[in->size] = 0;
}
static const char *read_input(void *payload, uint32_t index, TSPoint point, uint32_t *count) {
  (void)point;
  Input *in = payload;
  in->calls++;
  if (index < in->last) in->backward++;
  in->last = index;
  *count = index < in->size ? in->size - index : 0;
  if (*count > CHUNK) *count = CHUNK;
  in->delivered += *count;
  if (*count) for (uint32_t i = index / CHUNK; i <= (index + *count - 1) / CHUNK; i++) {
    if (!in->seen[i]) { in->seen[i] = 1; in->unique++; }
  }
  return index < in->size ? in->bytes + index : "";
}
static TSPoint point_at(const Input *in, uint32_t end) {
  TSPoint p = {0, 0};
  for (uint32_t i = 0; i < end; i++) {
    if (in->bytes[i] == '\n') { p.row++; p.column = 0; }
    else p.column++;
  }
  return p;
}
static TSInputEdit edit_for(const Input *a, const Input *b) {
  uint32_t start = 0, old_end = a->size, new_end = b->size;
  while (start < old_end && start < new_end && a->bytes[start] == b->bytes[start]) start++;
  while (old_end > start && new_end > start && a->bytes[old_end - 1] == b->bytes[new_end - 1]) {
    old_end--; new_end--;
  }
  /* Do not split a UTF-8 code point at an edit boundary. */
  while (start && start < a->size && ((unsigned char)a->bytes[start] & 0xc0) == 0x80) start--;
  while (old_end < a->size && ((unsigned char)a->bytes[old_end] & 0xc0) == 0x80) old_end++;
  while (new_end < b->size && ((unsigned char)b->bytes[new_end] & 0xc0) == 0x80) new_end++;
  return (TSInputEdit){start, old_end, new_end, point_at(a, start),
                       point_at(a, old_end), point_at(b, new_end)};
}
static void nodes(TSNode node, unsigned depth, unsigned *count) {
  const char *type = ts_node_type(node);
  bool wrapper = !strcmp(type, "document") || !strcmp(type, "pair");
  if (!wrapper) {
    if ((*count)++) putchar(',');
    printf("[\"%s\",%u,%u,%u]", type, ts_node_start_byte(node), ts_node_end_byte(node), depth);
  }
  if (!strcmp(type, "string")) return;  /* Scalar string span includes its escapes. */
  if (depth > 1024) abort();
  for (uint32_t i = 0; i < ts_node_named_child_count(node); i++)
    nodes(ts_node_named_child(node, i), depth + !wrapper, count);
}
static void print_read(const Input *in) {
  printf("{\"calls\":%" PRIu64 ",\"delivered_bytes\":%" PRIu64
         ",\"unique_256b_chunks\":%" PRIu64 ",\"backward_reads\":%" PRIu64 "}",
         in->calls, in->delivered, in->unique, in->backward);
}
int main(int argc, char **argv) {
  if (argc != 2 && argc != 3) return 2;
  Input *old = calloc(1, sizeof(Input)), *updated = calloc(1, sizeof(Input));
  if (!old || !updated) abort();
  load(old, argv[1]);
  if (argc == 3) load(updated, argv[2]);
  ts_set_allocator(hats_malloc, hats_calloc, hats_realloc, hats_free);
  hats_profile_begin();
  TSParser *parser = ts_parser_new();
  if (!parser || !ts_parser_set_language(parser, tree_sitter_json())) abort();
  HatsProfile setup = hats_profile_end();
  TSInput input = {.payload = old, .read = read_input, .encoding = TSInputEncodingUTF8};
  hats_profile_begin();
  TSTree *original = ts_parser_parse(parser, NULL, input);
  HatsProfile full = hats_profile_end();
  if (!original) abort();
  TSTree *result = original;
  HatsProfile incremental = {0};
  if (argc == 3) {
    TSInputEdit edit = edit_for(old, updated);
    input.payload = updated;
    hats_profile_begin();
    ts_tree_edit(original, &edit);
    result = ts_parser_parse(parser, original, input);
    incremental = hats_profile_end();
    if (!result) abort();
  }
  TSNode root = ts_tree_root_node(result);
  printf("{\"has_error\":%s,\"setup\":", ts_node_has_error(root) ? "true" : "false");
  hats_print_profile(&setup);
  printf(",\"full_parse\":"); hats_print_profile(&full);
  printf(",\"incremental_parse\":"); hats_print_profile(&incremental);
  printf(",\"full_reads\":"); print_read(old);
  printf(",\"incremental_reads\":"); print_read(updated);
  printf(",\"nodes\":["); unsigned count = 0; nodes(root, 0, &count); putchar(']');
  hats_profile_begin();
  if (result != original) ts_tree_delete(result);
  ts_tree_delete(original); ts_parser_delete(parser);
  HatsProfile cleanup = hats_profile_end();
  printf(",\"cleanup\":"); hats_print_profile(&cleanup);
  printf(",\"live_after_cleanup\":%" PRIu64 "}\n", hats_live_bytes());
  assert(!hats_live_bytes());
  free(old->bytes); free(updated->bytes); free(old); free(updated);
  return 0;
}
