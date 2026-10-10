"""Synthetic report-shape/rejection tests, not RTL or physical measurements."""
import copy
import unittest

from design_evidence import CASES, FIXED, POINTS, SERVICE_BASES, SERVICE_SEED, validate_study, validate_technology


def study_fixture():
    rows = []
    for point in POINTS:
        for base in SERVICE_BASES:
            for workload, case in CASES:
                cycles = 1100 if point[0] == "dual" else 1000
                rows.append({"point": point[0], "response_base": base, "workload": workload, "case": case,
                             "digest": {"schema": 1, "encoding": "hats-architectural-state-le64-v1",
                                        "events": 111, "retirements": 100, "memory_events": 10, "sha256": "0" * 64},
                             "metrics": {"cycles": cycles, "retired": 100, "requests": 10, "response_base": base,
                                         "service_seed": SERVICE_SEED, "acceptance_wait_sum": 15,
                                         "response_wait_sum": 10 * (base + 3), "dual_issue_cycles": 3 if point[0] == "dual" else 0,
                                         "issued_operations": 105, "execution_stall_cycles": 2,
                                         "completion_stall_cycles": 3, "rename_stall_cycles": 4,
                                         "checkpoint_stall_cycles": 5, "rob_stall_cycles": 6,
                                         "ready_sum": 100, "occupancy_sum": 200, "peak_occupancy": point[1],
                                         "minimum_free_registers": 4, "branches": 10, "branch_misses": 2,
                                         "redirects": 2, "late_rejected": 1},
                             "simulated_ipc": 100 / cycles, "baseline_cycles_over_candidate_cycles": 1000 / cycles})
    return {"status": "passed", "full_design_matrix": True,
            "claim_class": "actual_APE_RTL_matched_work_controlled_abstract_service",
            "points": [list(p) for p in POINTS], "fixed": dict(FIXED), "results": rows,
            "service": {"response_bases": list(SERVICE_BASES), "seed": SERVICE_SEED,
                        "acceptance_jitter": [0, 3], "response_jitter": [0, 7]}}


def technology_fixture():
    return [{"status": "passed_early_estimate", "claim_class": "early_Liberty_mapped_area_and_combinational_boundary_delay",
             "fixed": {"program_words": 1024, "checkpoints": 4, "execution_stages": 2, "generation_bits": 2,
                       "dispatch_width": 1, "writeback_width": 1, "retire_width": 1},
             "proof_controls": {"positive": "equivalent", "negative": "not_equivalent"},
             "constraints": {"mapping_delay_target_ps": 1000, "boundary_driver": "BUF_X1", "boundary_load_fF": 5,
                             "clock_constraints": None}, "tool_manifest": {"status": "built"}, "limits": ["synthetic fixture"],
             "points": [list(p) for p in POINTS],
             "results": [{"point": list(p), "comb_equivalence": "passed", "comb_boundary_delay_ps": 2500.0,
                          "comb_interface": {"inputs": 2, "outputs": 1, "latches": 0, "identical_ordered_names": True,
                                             "abstracted_internal_logic": False},
                          "meets_comb_mapping_target": False, "mapped_area_library_units": 100.0,
                          "sequential_area_library_units": 50.0, "mapped_cells": 30,
                          "statistics": {"design": {"area": 100.0, "sequential_area": 50.0,
                                                    "num_cells": 30, "num_memories": 0,
                                                    "num_cells_by_type": {"DFF_X1": 10, "AND2_X1": 20}}}} for p in POINTS]}]


class StudyEvidenceTests(unittest.TestCase):
    def test_complete_shape_and_honest_slowdown(self):
        rows = validate_study(study_fixture())
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[1]["runs"], 12)
        self.assertLess(rows[1]["equal_case_geometric_mean_cycle_ratio"], 1)

    def reject(self, mutate):
        report = study_fixture(); mutate(report)
        with self.assertRaises((ValueError, RuntimeError)):
            validate_study(report)

    def test_matrix_and_profile(self):
        self.reject(lambda r: r["results"].pop())
        self.reject(lambda r: r["results"].append(copy.deepcopy(r["results"][0])))
        self.reject(lambda r: r.update(full_design_matrix=False))
        self.reject(lambda r: r["fixed"].update(writeback_width=2))
        self.reject(lambda r: r["service"].update(response_bases=[2]))

    def test_work_service_and_ratio(self):
        self.reject(lambda r: r["results"][12]["digest"].update(events=112))
        self.reject(lambda r: r["results"][12]["metrics"].update(acceptance_wait_sum=16))
        self.reject(lambda r: r["results"][12]["metrics"].update(response_base=16))
        self.reject(lambda r: r["results"][12].update(simulated_ipc=1.0))
        self.reject(lambda r: r["results"][12].update(baseline_cycles_over_candidate_cycles=2.0))

    def test_real_dual_and_impossible_counts(self):
        self.reject(lambda r: r["results"][12]["metrics"].update(dual_issue_cycles=0))
        self.reject(lambda r: r["results"][0]["metrics"].update(dual_issue_cycles=1))
        self.reject(lambda r: r["results"][0]["metrics"].update(cycles=0))
        self.reject(lambda r: r["results"][0]["metrics"].update(retired=99))

    def test_counter_bounds_and_digest_identity(self):
        self.reject(lambda r: r["results"][0]["digest"].update(sha256="missing"))
        for update in ({"peak_occupancy": 9}, {"minimum_free_registers": 65},
                       {"rename_stall_cycles": 1001}, {"issued_operations": 99},
                       {"issued_operations": 1001}, {"ready_sum": 8001},
                       {"branch_misses": 11}, {"late_rejected": -1}, {"redirects": True}):
            self.reject(lambda r, update=update: r["results"][0]["metrics"].update(update))


class TechnologyEvidenceTests(unittest.TestCase):
    def test_estimate_may_miss_mapping_target(self):
        rows = validate_technology(technology_fixture())
        self.assertEqual(len(rows), 9)
        self.assertFalse(rows[0]["meets_comb_mapping_target"])

    def reject(self, mutate):
        reports = technology_fixture(); mutate(reports)
        with self.assertRaises((ValueError, RuntimeError)):
            validate_technology(reports)

    def test_matrix_and_constraints(self):
        self.reject(lambda r: r[0]["results"].pop())
        self.reject(lambda r: r.append(copy.deepcopy(r[0])))
        self.reject(lambda r: r[0]["constraints"].update(boundary_load_fF=0))
        self.reject(lambda r: r[0]["fixed"].update(program_words=65536))

    def test_unproven_or_mislabeled_qor(self):
        self.reject(lambda r: r[0]["proof_controls"].update(negative="timeout"))
        self.reject(lambda r: r[0]["results"][0]["comb_interface"].update(abstracted_internal_logic=True))
        self.reject(lambda r: r[0]["results"][0].update(comb_equivalence="timeout"))
        self.reject(lambda r: r[0]["results"][0].update(meets_comb_mapping_target=True))
        self.reject(lambda r: r[0]["results"][0].update(comb_boundary_delay_ps=0))
        self.reject(lambda r: r[0]["results"][0]["statistics"]["design"]["num_cells_by_type"].update({"$_AND_": 1}))


if __name__ == "__main__":
    unittest.main()
