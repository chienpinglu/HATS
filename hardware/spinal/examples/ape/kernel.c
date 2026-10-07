/* A real compiler-generated integer/control-flow program, not an agent benchmark. */
long ape_kernel(const long *values, unsigned long count) {
    long result = 0;
    for (unsigned long i = 0; i < count; ++i) {
        long value = values[i];
        if (value & 1) result += value;
    }
    return result;
}
