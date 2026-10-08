/* Compile this file WITHOUT instrumentation or atomic macro substitutions. */
#include "profile.h"
#include "atomic_profile.h"
#include <assert.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Exact unique-line set for this bounded experiment, not a cache simulation. */
#define SLOTS (1u << 20)
static uintptr_t lines[SLOTS];
static bool active, have_last;
static uintptr_t last;
static unsigned phase;
static uint64_t loads, stores, bytes, unique, touches, same, adjacent, reused;
static uint64_t incs, decs, atomic_reads;
void hats_base_profile_begin(void);
HatsProfile hats_base_profile_end(void);

static void access_memory(const void *address, unsigned size, bool store) {
  if (!active) return;
  assert(size && (uintptr_t)address <= UINTPTR_MAX - size);
  if (store) stores++; else loads++;
  bytes += size;
  uintptr_t first = (uintptr_t)address / 64, end = ((uintptr_t)address + size - 1) / 64;
  for (uintptr_t line = first; line <= end; line++) {
    uintptr_t key = line + 1;
    size_t slot = (line * UINT64_C(11400714819323198485)) & (SLOTS - 1);
    size_t probes = 0;
    while (lines[slot] && lines[slot] != key) {
      if (++probes == SLOTS) abort(); /* Never silently drop observations. */
      slot = (slot + 1) & (SLOTS - 1);
    }
    if (!lines[slot]) { lines[slot] = key; unique++; } else reused++;
    touches++;
    if (have_last) {
      if (line == last) same++;
      if (line + 1 == last || last + 1 == line) adjacent++;
    }
    have_last = true; last = line;
  }
}
#define HOOK(N, T) \
  void __sanitizer_cov_load##N(T *p) { access_memory(p, N, false); } \
  void __sanitizer_cov_store##N(T *p) { access_memory(p, N, true); }
HOOK(1, uint8_t)
HOOK(2, uint16_t)
HOOK(4, uint32_t)
HOOK(8, uint64_t)
HOOK(16, __int128)

uint32_t hats_atomic_add_fetch(volatile uint32_t *p, uint32_t n, int order) {
  assert(order == __ATOMIC_SEQ_CST);
  if (active) incs++;
  return __atomic_add_fetch(p, n, __ATOMIC_SEQ_CST);
}
uint32_t hats_atomic_sub_fetch(volatile uint32_t *p, uint32_t n, int order) {
  assert(order == __ATOMIC_SEQ_CST);
  if (active) decs++;
  return __atomic_sub_fetch(p, n, __ATOMIC_SEQ_CST);
}
size_t hats_atomic_load_n(const volatile size_t *p, int order) {
  assert(order == __ATOMIC_RELAXED);
  if (active) atomic_reads++;
  return __atomic_load_n(p, __ATOMIC_RELAXED);
}
void hats_profile_begin(void) {
  assert(!active);
  memset(lines, 0, sizeof lines);
  loads = stores = bytes = unique = touches = same = adjacent = reused = 0;
  incs = decs = atomic_reads = 0; have_last = false;
  hats_base_profile_begin(); active = true;
}
HatsProfile hats_profile_end(void) {
  assert(active); active = false;
  HatsProfile result = hats_base_profile_end();
  fprintf(stderr, "{\"phase\":%u,\"loads\":%" PRIu64 ",\"stores\":%" PRIu64
      ",\"access_bytes\":%" PRIu64 ",\"unique_64b_lines\":%" PRIu64
      ",\"line_touches\":%" PRIu64 ",\"reused_line_touches\":%" PRIu64
      ",\"consecutive_same_line\":%" PRIu64 ",\"consecutive_adjacent_line\":%" PRIu64
      ",\"atomic_inc_seqcst\":%" PRIu64 ",\"atomic_dec_seqcst\":%" PRIu64
      ",\"atomic_load_relaxed\":%" PRIu64 "}\n",
      phase++, loads, stores, bytes, unique, touches, reused, same, adjacent,
      incs, decs, atomic_reads);
  return result;
}
