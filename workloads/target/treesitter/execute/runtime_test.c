/* Single-hart target runtime tests; no host replacement of allocator/atomics. */
#include "platform.h"
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/times.h>
#include <sys/types.h>
void *_sbrk(ptrdiff_t);
uint32_t hats_fetch_add(volatile void *, uint32_t, int) __asm__("__atomic_fetch_add_4");
uint32_t hats_fetch_sub(volatile void *, uint32_t, int) __asm__("__atomic_fetch_sub_4");
uint64_t hats_load(const volatile void *, int) __asm__("__atomic_load_8");
int _read(int, void *, size_t);
int _write(int, const void *, size_t);
int _close(int);
off_t _lseek(int, off_t, int);
int _fstat(int, struct stat *);
int _isatty(int);
clock_t _times(struct tms *);
int _getpid(void);
int _kill(int, int);
#define CHECK(x) do { if (!(x)) hats_finish(HATS_RUNTIME_FAILURE); hats_result->count++; } while (0)
uint64_t ape_main(const HatsArguments *args) {
  *hats_result = (HatsResult){.magic = HATS_MAGIC};
  hats_heap_limit = args->heap_limit;
  CHECK(hats_heap_limit == 65536);
  CHECK(_sbrk(16) == (void *)HATS_HEAP);
  CHECK(_sbrk(-16) == (void *)(HATS_HEAP + 16));
  CHECK(_sbrk(-1) == (void *)-1 && errno == ENOMEM);
  CHECK(_sbrk(65537) == (void *)-1 && errno == ENOMEM);
  CHECK(_sbrk(0) == (void *)HATS_HEAP);
  volatile uint32_t counter = UINT32_MAX;
  CHECK(hats_fetch_add(&counter, 1, __ATOMIC_SEQ_CST) == UINT32_MAX && counter == 0);
  CHECK(hats_fetch_sub(&counter, 1, __ATOMIC_SEQ_CST) == 0 && counter == UINT32_MAX);
  volatile uint64_t flag = UINT64_C(0x8000000000000042);
  CHECK(hats_load(&flag, __ATOMIC_RELAXED) == flag);
  unsigned char *p = hats_calloc(16, 4);
  CHECK((uintptr_t)p % _Alignof(max_align_t) == 0);
  for (unsigned i = 0; i < 64; i++) { CHECK(p[i] == 0); p[i] = (unsigned char)i; }
  p = hats_realloc(p, 4096);
  for (unsigned i = 0; i < 64; i++) CHECK(p[i] == i);
  p = hats_realloc(p, 8);
  for (unsigned i = 0; i < 8; i++) CHECK(p[i] == i);
  hats_free(p); hats_free(NULL);
  p = hats_realloc(NULL, 32); CHECK(p != NULL); CHECK(hats_realloc(p, 0) == NULL);
  CHECK(_read(0, NULL, 0) == -1 && errno == EBADF);
  CHECK(_close(7) == -1 && errno == EBADF);
  CHECK(_lseek(1, 0, 0) == -1 && errno == ESPIPE);
  CHECK(_times(NULL) == (clock_t)-1 && errno == ENOSYS);
  CHECK(_getpid() == 1 && _kill(1, 9) == -1 && errno == ENOSYS);
  struct stat st;
  CHECK(_fstat(1, &st) == 0 && (st.st_mode & S_IFMT) == S_IFCHR);
  CHECK(_fstat(0, &st) == -1 && errno == EBADF);
  CHECK(_isatty(2) == 1 && _isatty(0) == 0 && errno == EBADF);
  CHECK(_write(0, "x", 1) == -1 && errno == EBADF);
  CHECK(_write(1, "test", 4) == 4);
  char diagnostic[4096]; memset(diagnostic, 'x', sizeof diagnostic);
  CHECK(_write(2, diagnostic, sizeof diagnostic) == 4092);
  CHECK(_write(1, "x", 1) == -1 && errno == ENOSPC);
  hats_finish(HATS_OK);
}
