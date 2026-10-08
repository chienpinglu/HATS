/* Original HATS host instrumentation. Compile separately without coverage or
 * function instrumentation. Counts are diagnostics, not target cycle estimates. */
#include "profile.h"
#include <assert.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef union { max_align_t alignment; struct { size_t size; uint64_t magic; } h; } Header;
static const uint64_t magic = UINT64_C(0x48415453414c4c4f);
static uint64_t live;
static bool active;
static HatsProfile p;
static uint64_t wall_start, cpu_start;
static uintptr_t stack_low, stack_high;
static uint64_t depth;
#define MAX_EDGES 65536
static uint32_t edges[MAX_EDGES], edge_count;

static uint64_t now(clockid_t clock) {
  struct timespec t;
  if (clock_gettime(clock, &t)) abort();
  return (uint64_t)t.tv_sec * UINT64_C(1000000000) + t.tv_nsec;
}
static void account(size_t old, size_t size) {
  assert(live >= old);
  live = live - old + size;
  if (active) {
    if (live > p.peak_live) p.peak_live = live;
    p.allocated_bytes += size;
  }
}
void *hats_malloc(size_t size) {
  if (size > SIZE_MAX - sizeof(Header) || size > 256u * 1024u * 1024u) abort();
  Header *h = malloc(sizeof(Header) + size);
  if (!h) abort();
  h->h.size = size; h->h.magic = magic;
  account(0, size);
  if (active) p.alloc_calls++;
  return h + 1;
}
void *hats_calloc(size_t n, size_t size) {
  if (n && size > SIZE_MAX / n) abort();
  void *ptr = hats_malloc(n * size);
  memset(ptr, 0, n * size);
  return ptr;
}
void hats_free(void *ptr) {
  if (!ptr) return;
  Header *h = (Header *)ptr - 1;
  assert(h->h.magic == magic);
  account(h->h.size, 0);
  if (active) p.free_calls++;
  h->h.magic = 0;
  free(h);
}
void *hats_realloc(void *ptr, size_t size) {
  if (!ptr) return hats_malloc(size);
  if (!size) { hats_free(ptr); return NULL; }
  if (size > SIZE_MAX - sizeof(Header) || size > 256u * 1024u * 1024u) abort();
  Header *old = (Header *)ptr - 1;
  assert(old->h.magic == magic);
  size_t old_size = old->h.size;
  Header *h = realloc(old, sizeof(Header) + size);
  if (!h) abort();
  h->h.size = size; h->h.magic = magic;
  account(old_size, size);
  if (active) p.realloc_calls++;
  return h + 1;
}
void hats_profile_begin(void) {
  assert(!active && depth == 0);
  memset(&p, 0, sizeof p);
  memset(edges, 0, sizeof edges);
  p.live_start = p.peak_live = live;
  stack_low = UINTPTR_MAX; stack_high = 0;
  wall_start = now(CLOCK_MONOTONIC);
  cpu_start = now(CLOCK_PROCESS_CPUTIME_ID);
  active = true;
}
HatsProfile hats_profile_end(void) {
  assert(active && depth == 0);
  active = false;
  p.cpu_ns = now(CLOCK_PROCESS_CPUTIME_ID) - cpu_start;
  p.ns = now(CLOCK_MONOTONIC) - wall_start;
  p.live_end = live;
  if (stack_high) p.sampled_stack_span = stack_high - stack_low;
  return p;
}
uint64_t hats_live_bytes(void) { return live; }
void __sanitizer_cov_trace_pc_guard_init(uint32_t *start, uint32_t *end) {
  if (start == end || *start) return;
  for (uint32_t *q = start; q < end; q++) {
    if (++edge_count >= MAX_EDGES) abort();
    *q = edge_count;
  }
}
void __sanitizer_cov_trace_pc_guard(uint32_t *guard) {
  if (!active) return;
  assert(*guard && *guard < MAX_EDGES);
  if (!edges[*guard]) { edges[*guard] = 1; p.unique_edges++; }
  p.edge_visits++;
}
void __cyg_profile_func_enter(void *fn, void *caller) {
  (void)fn; (void)caller;
  if (!active) return;
  volatile char sample;
  uintptr_t address = (uintptr_t)&sample;
  if (address < stack_low) stack_low = address;
  if (address > stack_high) stack_high = address;
  p.function_entries++;
  if (++depth > p.max_call_depth) p.max_call_depth = depth;
}
void __cyg_profile_func_exit(void *fn, void *caller) {
  (void)fn; (void)caller;
  if (active) { assert(depth); depth--; }
}
void hats_print_profile(const HatsProfile *q) {
  printf("{\"wall_ns\":%" PRIu64 ",\"cpu_ns\":%" PRIu64
         ",\"alloc_calls\":%" PRIu64 ",\"realloc_calls\":%" PRIu64
         ",\"free_calls\":%" PRIu64 ",\"allocated_bytes\":%" PRIu64
         ",\"live_start\":%" PRIu64 ",\"live_end\":%" PRIu64
         ",\"peak_live\":%" PRIu64 ",\"edge_visits\":%" PRIu64
         ",\"unique_edges\":%" PRIu64 ",\"function_entries\":%" PRIu64
         ",\"max_call_depth\":%" PRIu64 ",\"sampled_stack_span\":%" PRIu64 "}",
         q->ns, q->cpu_ns, q->alloc_calls, q->realloc_calls, q->free_calls,
         q->allocated_bytes, q->live_start, q->live_end, q->peak_live,
         q->edge_visits, q->unique_edges, q->function_entries,
         q->max_call_depth, q->sampled_stack_span);
}
