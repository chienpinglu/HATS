#ifndef HATS_TS_PROFILE_H
#define HATS_TS_PROFILE_H
#include <stddef.h>
#include <stdint.h>

typedef struct {
  uint64_t ns, cpu_ns, alloc_calls, realloc_calls, free_calls, allocated_bytes;
  uint64_t live_start, live_end, peak_live, edge_visits, unique_edges;
  uint64_t function_entries, max_call_depth, sampled_stack_span;
} HatsProfile;
void *hats_malloc(size_t);
void *hats_calloc(size_t, size_t);
void *hats_realloc(void *, size_t);
void hats_free(void *);
void hats_profile_begin(void);
HatsProfile hats_profile_end(void);
uint64_t hats_live_bytes(void);
void hats_print_profile(const HatsProfile *);
#endif
