/* Bounded C port of microsoft/stop tasks/maxcut/seed_algorithm.py.
 * Copyright (c) Microsoft Corporation. MIT license; see STOP_LICENSE.txt.
 * Port and fixed-buffer ABI: HATS contributors, 2026.
 * Nonnegative weights, 1 <= n <= 32, each weight <= 65535.
 * Scan ascending node IDs and partition 0 before 1, preserving seed tie order
 * for the validated bounded CPython integer-set inputs. No malloc or syscalls.
 */
typedef unsigned long long u64;
typedef long long i64;
struct Job { u64 n; const u64 *weights; i64 *partition; };

u64 hats_maxcut(const struct Job *job) {
    u64 n = job->n;
    const u64 *weights = job->weights;
    i64 *partition = job->partition;
    for (u64 i = 0; i < n; ++i) partition[i] = -1;
    for (u64 remaining = n; remaining != 0; --remaining) {
        i64 best_weight = -1;
        u64 best_node = 0;
        i64 best_partition = 0;
        for (u64 node = 0; node < n; ++node) {
            if (partition[node] != -1) continue;
            for (i64 side = 0; side < 2; ++side) {
                i64 cut_weight = 0;
                for (u64 neighbor = 0; neighbor < n; ++neighbor) {
                    if (partition[neighbor] == 1 - side)
                        cut_weight += weights[node * n + neighbor];
                }
                if (cut_weight > best_weight) {
                    best_weight = cut_weight;
                    best_node = node;
                    best_partition = side;
                }
            }
        }
        partition[best_node] = best_partition;
    }
#ifdef HATS_TARGET
    __asm__ volatile("mov x0, %0\n\tbrk #0" : : "r"(n) : "x0");
    __builtin_unreachable();
#else
    return n;
#endif
}
