/* Actual RV64 helper execution; expected arithmetic is supplied by Python big
 * integers outside this binary, not by a duplicate target implementation. */
#include "platform.h"
uint64_t __muldi3(uint64_t, uint64_t);
uint64_t __udivdi3(uint64_t, uint64_t);
uint64_t __umoddi3(uint64_t, uint64_t);
int64_t __moddi3(int64_t, int64_t);
__uint128_t __multi3(__uint128_t, __uint128_t);
typedef union { __uint128_t value; struct { uint64_t lo, hi; } limb; } U128;
uint64_t ape_main(const HatsArguments *args) {
  volatile HatsResult *result = (volatile HatsResult *)HATS_OUTPUT;
  if ((uintptr_t)args != HATS_ARGUMENT || args->old_bytes > 256) return 1;
  const uint64_t (*in)[4] = (const uint64_t (*)[4])HATS_OLD;
  volatile uint64_t (*out)[6] = (volatile uint64_t (*)[6])(HATS_OUTPUT + sizeof(HatsResult));
  *result = (HatsResult){.magic = HATS_MAGIC, .count = args->old_bytes};
  for (uint64_t i = 0; i < args->old_bytes; i++) {
    U128 a = {.limb = {in[i][0], in[i][1]}}, b = {.limb = {in[i][2], in[i][3]}};
    U128 product = {.value = __multi3(a.value, b.value)};
    out[i][0] = __muldi3(a.limb.lo, b.limb.lo);
    out[i][1] = __udivdi3(a.limb.lo, b.limb.lo);
    out[i][2] = __umoddi3(a.limb.lo, b.limb.lo);
    out[i][3] = (uint64_t)__moddi3((int64_t)a.limb.lo, (int64_t)b.limb.lo);
    out[i][4] = product.limb.lo; out[i][5] = product.limb.hi;
  }
  return 0;
}
