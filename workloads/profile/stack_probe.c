/* Native touched-stack extent, including adapter, libc and pthread startup.
 * NOT a worst-case bound: reserved/unwritten bytes and sentinel collisions are
 * invisible. Guard pages make exceeding this experiment's stack fail loudly. */
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

int hats_baseline_main(int, char **);
typedef struct { int argc; char **argv; unsigned char *base; size_t size; int result; } Args;
static void *worker(void *ptr) {
  Args *a = ptr;
  volatile char marker;
  assert((uintptr_t)&marker >= (uintptr_t)a->base &&
         (uintptr_t)&marker < (uintptr_t)a->base + a->size);
  a->result = hats_baseline_main(a->argc, a->argv);
  return NULL;
}
int main(int argc, char **argv) {
  size_t page = (size_t)sysconf(_SC_PAGESIZE), size = 2u * 1024u * 1024u;
  unsigned char *mapping = mmap(NULL, size + 2 * page, PROT_NONE,
                               MAP_PRIVATE | MAP_ANON, -1, 0);
  assert(mapping != MAP_FAILED);
  unsigned char *base = mapping + page;
  assert(!mprotect(base, size, PROT_READ | PROT_WRITE));
  memset(base, 0xa5, size);
  pthread_attr_t attr; pthread_t thread;
  assert(!pthread_attr_init(&attr));
  assert(!pthread_attr_setstack(&attr, base, size));
  Args a = {argc, argv, base, size, -1};
  assert(!pthread_create(&thread, &attr, worker, &a));
  assert(!pthread_join(thread, NULL));
  size_t untouched = 0;
  while (untouched < size && base[untouched] == 0xa5) untouched++;
  assert(untouched > 0 && untouched < size);
  fprintf(stderr, "{\"stack_capacity_bytes\":%zu,\"observed_touched_extent_bytes\":%zu}\n",
          size, size - untouched);
  assert(!pthread_attr_destroy(&attr));
  assert(!munmap(mapping, size + 2 * page));
  return a.result;
}
