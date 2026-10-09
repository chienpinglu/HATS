/* Original target adapter. Actual parsing/editing/traversal is upstream C.
 * Full typed byte spans and depth are returned; no checksum-only correctness. */
#include "platform.h"
#include <tree_sitter/api.h>
#include <string.h>
const TSLanguage *tree_sitter_json(void);
typedef struct { const char *bytes; uint32_t size; } Input;
static uint64_t output_limit;

static const char *read_input(void *context, uint32_t index, TSPoint point, uint32_t *count) {
  (void)point; const Input *input = context;
  *count = index < input->size ? input->size - index : 0;
  if (*count > 256) *count = 256;
  return index < input->size ? input->bytes + index : "";
}
static TSPoint point_at(const Input *input, uint32_t end) {
  TSPoint point = {0, 0};
  for (uint32_t i = 0; i < end; i++) {
    if (input->bytes[i] == '\n') { point.row++; point.column = 0; }
    else point.column++;
  }
  return point;
}
static TSInputEdit edit_for(const Input *old, const Input *updated) {
  uint32_t start = 0, old_end = old->size, new_end = updated->size;
  while (start < old_end && start < new_end && old->bytes[start] == updated->bytes[start]) start++;
  while (old_end > start && new_end > start && old->bytes[old_end-1] == updated->bytes[new_end-1]) {
    old_end--; new_end--;
  }
  while (start && start < old->size && ((unsigned char)old->bytes[start] & 0xc0) == 0x80) start--;
  while (old_end < old->size && ((unsigned char)old->bytes[old_end] & 0xc0) == 0x80) old_end++;
  while (new_end < updated->size && ((unsigned char)updated->bytes[new_end] & 0xc0) == 0x80) new_end++;
  return (TSInputEdit){start, old_end, new_end, point_at(old, start), point_at(old, old_end), point_at(updated, new_end)};
}
static void nodes(TSNode node, uint32_t depth) {
  const char *type = ts_node_type(node);
  int wrapper = !strcmp(type, "document") || !strcmp(type, "pair");
  if (depth > 1024) hats_finish(HATS_BAD_TREE);
  if (!wrapper) {
    static const char *const types[] = {"array", "object", "string", "number", "true", "false", "null"};
    uint32_t kind = 0;
    while (kind < 7 && strcmp(type, types[kind])) kind++;
    if (kind == 7) hats_finish(HATS_BAD_TREE);
    uint64_t count = hats_result->count;
    if (count >= (output_limit - sizeof(HatsResult)) / sizeof(HatsNode)) hats_finish(HATS_OUTPUT_FULL);
    volatile HatsNode *out = (volatile HatsNode *)(HATS_OUTPUT + sizeof(HatsResult));
    out[count] = (HatsNode){kind + 1, ts_node_start_byte(node), ts_node_end_byte(node), depth};
    hats_result->count = count + 1;
  }
  if (!strcmp(type, "string")) return;
  for (uint32_t i = 0; i < ts_node_named_child_count(node); i++)
    nodes(ts_node_named_child(node, i), depth + !wrapper);
}
uint64_t ape_main(const HatsArguments *args) {
  *hats_result = (HatsResult){.magic = HATS_MAGIC, .status = UINT64_MAX};
  if ((uintptr_t)args != HATS_ARGUMENT || args->magic != HATS_MAGIC || args->mode > 1 ||
      args->old_bytes > HATS_INPUT_MAX || args->new_bytes > HATS_INPUT_MAX ||
      (!args->mode && args->new_bytes) || args->heap_limit > HATS_HEAP_BYTES ||
      args->output_limit < sizeof(HatsResult) || args->output_limit > HATS_OUTPUT_BYTES ||
      args->reserved0 || args->reserved1) hats_finish(HATS_BAD_ARGUMENT);
  hats_heap_limit = args->heap_limit; output_limit = args->output_limit;
  Input old = {(const char *)HATS_OLD, (uint32_t)args->old_bytes};
  Input updated = {(const char *)HATS_NEW, (uint32_t)args->new_bytes};
  ts_set_allocator(hats_malloc, hats_calloc, hats_realloc, hats_free);
  TSParser *parser = ts_parser_new();
  if (!parser || !ts_parser_set_language(parser, tree_sitter_json())) hats_finish(HATS_RUNTIME_FAILURE);
  TSInput input = {.payload = &old, .read = read_input, .encoding = TSInputEncodingUTF8};
  TSTree *original = ts_parser_parse(parser, NULL, input);
  if (!original) hats_finish(HATS_RUNTIME_FAILURE);
  TSTree *result = original;
  if (args->mode) {
    TSInputEdit edit = edit_for(&old, &updated);
    ts_tree_edit(original, &edit); input.payload = &updated;
    result = ts_parser_parse(parser, original, input);
    if (!result) hats_finish(HATS_RUNTIME_FAILURE);
  }
  TSNode root = ts_tree_root_node(result);
  hats_result->has_error = ts_node_has_error(root);
  /* Error recovery structure is not part of the frozen independent contract. */
  if (!hats_result->has_error) nodes(root, 0);
  if (result != original) ts_tree_delete(result);
  ts_tree_delete(original); ts_parser_delete(parser);
  hats_finish(HATS_OK);
}
