/* Original isolated single-hart service provider for Newlib/Tree-sitter.
 * No interrupts, second hart, DMA/shared-tree writer or host callback is allowed
 * in this profile. Atomic helpers rely on that exclusion, not an A extension. */
#include "platform.h"
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/times.h>
#include <sys/types.h>

volatile HatsResult *const hats_result = (volatile HatsResult *)HATS_OUTPUT;
uint64_t hats_heap_limit;
static uint64_t granted, live, peak, allocations;
typedef union { max_align_t align; struct { size_t bytes; uint64_t magic; } info; } Header;
#define ALLOC_MAGIC UINT64_C(0x4841545348454150)

void hats_finish(uint64_t status) {
  hats_result->status = status;
  hats_result->live_bytes = live; hats_result->peak_bytes = peak;
  hats_result->allocation_calls = allocations; hats_result->heap_granted = granted;
  __asm__ volatile("mv a0, %0; j ape_exit" :: "r"(status) : "a0", "memory");
  __builtin_unreachable();
}
void *_sbrk(ptrdiff_t increment) {
  /* Newlib may return a free top chunk using a negative increment. */
  uint64_t old = granted;
  if (increment < 0) {
    uint64_t decrease = 0 - (uint64_t)increment;
    if (decrease > granted) { errno = ENOMEM; return (void *)-1; }
    granted -= decrease;
  } else {
    if ((uint64_t)increment > hats_heap_limit - granted) { errno = ENOMEM; return (void *)-1; }
    granted += (uint64_t)increment;
  }
  return (void *)(uintptr_t)(HATS_HEAP + old);
}
static void update(size_t old, size_t now) {
  if (live < old) hats_finish(HATS_RUNTIME_FAILURE);
  live = live - old + now;
  if (live > peak) peak = live;
}
void *hats_malloc(size_t size) {
  if (size > SIZE_MAX - sizeof(Header)) hats_finish(HATS_NO_MEMORY);
  Header *p = malloc(size + sizeof(Header));
  if (!p) hats_finish(HATS_NO_MEMORY);
  p->info.bytes = size; p->info.magic = ALLOC_MAGIC;
  update(0, size); allocations++;
  return p + 1;
}
void *hats_calloc(size_t n, size_t size) {
  if (n && size > SIZE_MAX / n) hats_finish(HATS_NO_MEMORY);
  void *p = hats_malloc(n * size); memset(p, 0, n * size); return p;
}
void hats_free(void *p) {
  if (!p) return;
  Header *h = (Header *)p - 1;
  if (h->info.magic != ALLOC_MAGIC) hats_finish(HATS_RUNTIME_FAILURE);
  update(h->info.bytes, 0); h->info.magic = 0; free(h);
}
void *hats_realloc(void *p, size_t size) {
  if (!p) return hats_malloc(size);
  if (!size) { hats_free(p); return NULL; }
  if (size > SIZE_MAX - sizeof(Header)) hats_finish(HATS_NO_MEMORY);
  Header *old = (Header *)p - 1;
  if (old->info.magic != ALLOC_MAGIC) hats_finish(HATS_RUNTIME_FAILURE);
  size_t old_size = old->info.bytes;
  Header *h = realloc(old, size + sizeof(Header));
  if (!h) hats_finish(HATS_NO_MEMORY);
  h->info.bytes = size; h->info.magic = ALLOC_MAGIC; update(old_size, size);
  return h + 1;
}

/* Keep the compiler's helper ABI. Atomicity comes from the single-agent profile;
 * fences preserve ordering. These symbols must not be reused for shared access. */
uint32_t hats_fetch_add(volatile void *p, uint32_t n, int order) __asm__("__atomic_fetch_add_4");
uint32_t hats_fetch_sub(volatile void *p, uint32_t n, int order) __asm__("__atomic_fetch_sub_4");
uint64_t hats_load(const volatile void *p, int order) __asm__("__atomic_load_8");
static void check_atomic(const volatile void *p, unsigned alignment, int order) {
  if ((uintptr_t)p % alignment || (order != __ATOMIC_RELAXED && order != __ATOMIC_SEQ_CST))
    hats_finish(HATS_RUNTIME_FAILURE);
  __asm__ volatile("fence rw,rw" ::: "memory");
}
uint32_t hats_fetch_add(volatile void *p, uint32_t n, int order) {
  check_atomic(p, 4, order);
  volatile uint32_t *v = p; uint32_t old = *v; *v = old + n;
  __asm__ volatile("fence rw,rw" ::: "memory"); return old;
}
uint32_t hats_fetch_sub(volatile void *p, uint32_t n, int order) {
  check_atomic(p, 4, order);
  volatile uint32_t *v = p; uint32_t old = *v; *v = old - n;
  __asm__ volatile("fence rw,rw" ::: "memory"); return old;
}
uint64_t hats_load(const volatile void *p, int order) {
  check_atomic(p, 8, order); uint64_t value = *(const volatile uint64_t *)p;
  __asm__ volatile("fence rw,rw" ::: "memory"); return value;
}

/* Bounded target-resident diagnostic streams only; no filesystem/process host
 * emulation. Optional unsupported services return honest errors. */
static char diagnostics[4096];
static size_t diagnostic_used;
int _write(int fd, const void *p, size_t count) {
  if (fd != 1 && fd != 2) { errno = EBADF; return -1; }
  size_t available = sizeof diagnostics - diagnostic_used;
  if (!available) { errno = ENOSPC; return -1; }
  if (count > available) count = available;
  memcpy(diagnostics + diagnostic_used, p, count); diagnostic_used += count;
  return (int)count;
}
int _read(int fd, void *p, size_t count) { (void)fd; (void)p; (void)count; errno = EBADF; return -1; }
int _close(int fd) { (void)fd; errno = EBADF; return -1; }
off_t _lseek(int fd, off_t offset, int whence) { (void)fd; (void)offset; (void)whence; errno = ESPIPE; return -1; }
int _fstat(int fd, struct stat *st) {
  if (fd != 1 && fd != 2) { errno = EBADF; return -1; }
  memset(st, 0, sizeof *st); st->st_mode = S_IFCHR; return 0;
}
int _isatty(int fd) { if (fd == 1 || fd == 2) return 1; errno = EBADF; return 0; }
clock_t _times(struct tms *t) { (void)t; errno = ENOSYS; return (clock_t)-1; }
int _getpid(void) { return 1; } /* sole isolated application context */
int _kill(int pid, int signal) { (void)pid; (void)signal; errno = ENOSYS; return -1; }
void _exit(int status) { (void)status; hats_finish(HATS_RUNTIME_FAILURE); }
