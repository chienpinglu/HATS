/* Original deterministic calibration, not a workload measurement. */
#include "profile.h"
#include "atomic_profile.h"
#include <assert.h>
#include <stdint.h>
void __sanitizer_cov_load1(uint8_t *);
void __sanitizer_cov_load16(__int128 *);
void __sanitizer_cov_store8(uint64_t *);
int main(void) {
  _Alignas(64) unsigned char memory[128] = {0};
  uint32_t count = 7; size_t value = 42;
  hats_profile_begin();
  __sanitizer_cov_load1(memory);
  __sanitizer_cov_store8((uint64_t *)(memory + 64));
  __sanitizer_cov_load16((__int128 *)(memory + 56));
  assert(hats_atomic_add_fetch(&count, 2, __ATOMIC_SEQ_CST) == 9);
  assert(hats_atomic_sub_fetch(&count, 1, __ATOMIC_SEQ_CST) == 8);
  assert(hats_atomic_load_n(&value, __ATOMIC_RELAXED) == 42);
  (void)hats_profile_end();
  hats_profile_begin();
  (void)hats_profile_end();
  return 0;
}
