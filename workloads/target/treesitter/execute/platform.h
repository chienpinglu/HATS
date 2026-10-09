/* Original bounded single-hart APE application ABI; not a Linux/POSIX ABI. */
#ifndef HATS_TS_PLATFORM_H
#define HATS_TS_PLATFORM_H
#include <stddef.h>
#include <stdint.h>
#define HATS_MAGIC UINT64_C(0x4841545354533031)
#define HATS_DATA_BASE UINT64_C(0x100000)
#define HATS_DATA_END UINT64_C(0x1100000)
#define HATS_ARGUMENT UINT64_C(0x180000)
#define HATS_OLD UINT64_C(0x181000)
#define HATS_NEW UINT64_C(0x1c1000)
#define HATS_INPUT_MAX UINT64_C(0x3f000)
#define HATS_OUTPUT UINT64_C(0x210000)
#define HATS_OUTPUT_BYTES UINT64_C(0xf0000)
#define HATS_HEAP UINT64_C(0x400000)
#define HATS_HEAP_BYTES UINT64_C(0xa00000)
#define HATS_STACK_BASE UINT64_C(0xf00000)
#define HATS_STACK_TOP UINT64_C(0x1000000)
typedef struct {
  uint64_t magic, mode, old_bytes, new_bytes, heap_limit, output_limit, reserved0, reserved1;
} HatsArguments;
typedef struct {
  uint64_t magic, status, has_error, count, live_bytes, peak_bytes, allocation_calls, heap_granted;
} HatsResult;
typedef struct { uint32_t type, start, end, depth; } HatsNode;
enum { HATS_OK = 0, HATS_BAD_ARGUMENT = 1, HATS_NO_MEMORY = 2,
       HATS_OUTPUT_FULL = 3, HATS_BAD_TREE = 4, HATS_RUNTIME_FAILURE = 5 };
extern volatile HatsResult *const hats_result;
extern uint64_t hats_heap_limit;
void hats_finish(uint64_t status) __attribute__((noreturn));
void *hats_malloc(size_t);
void *hats_calloc(size_t, size_t);
void *hats_realloc(void *, size_t);
void hats_free(void *);
#endif
