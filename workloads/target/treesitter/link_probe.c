/* Original link-reachability probe, not startup code or a validated application.
 * Keep the native baseline's parse/edit/traversal/cleanup API families reachable.
 * Inputs/output storage would have to be prepared by a real target ABI adapter. */
#include <tree_sitter/api.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

const TSLanguage *tree_sitter_json(void);
typedef struct { const char *data; uint32_t size; } Buffer;
typedef struct {
  Buffer old_input, new_input;
  TSInputEdit edit;
  uint32_t incremental;
  volatile uint64_t semantic_nodes, span_checksum, has_error;
} Arguments;

static const char *read_input(void *payload, uint32_t offset, TSPoint point, uint32_t *bytes) {
  (void)point;
  const Buffer *b = payload;
  *bytes = offset < b->size ? b->size - offset : 0;
  if (*bytes > 256) *bytes = 256;
  return offset < b->size ? b->data + offset : "";
}
static void visit(TSNode n, unsigned depth, Arguments *a) {
  const char *type = ts_node_type(n);
  unsigned wrapper = !strcmp(type, "document") || !strcmp(type, "pair");
  if (depth > 1024) abort();
  if (!wrapper) {
    a->semantic_nodes++;
    a->span_checksum += ts_node_start_byte(n) + ts_node_end_byte(n) + depth;
  }
  if (!strcmp(type, "string")) return;
  for (uint32_t i = 0; i < ts_node_named_child_count(n); ++i)
    visit(ts_node_named_child(n, i), depth + !wrapper, a);
}

void hats_tool_entry(Arguments *a) {
  ts_set_allocator(malloc, calloc, realloc, free);
  TSParser *parser = ts_parser_new();
  if (!parser || !ts_parser_set_language(parser, tree_sitter_json())) abort();
  TSInput input = {.payload = &a->old_input, .read = read_input, .encoding = TSInputEncodingUTF8};
  TSTree *old = ts_parser_parse(parser, NULL, input);
  if (!old) abort();
  TSTree *result = old;
  if (a->incremental) {
    ts_tree_edit(old, &a->edit);
    input.payload = &a->new_input;
    result = ts_parser_parse(parser, old, input);
    if (!result) abort();
  }
  a->semantic_nodes = a->span_checksum = 0;
  a->has_error = ts_node_has_error(ts_tree_root_node(result));
  visit(ts_tree_root_node(result), 0, a);
  if (result != old) ts_tree_delete(result);
  ts_tree_delete(old);
  ts_parser_delete(parser);
}
