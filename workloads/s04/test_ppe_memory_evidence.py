"""Synthetic report rejection tests only; these are not hardware execution."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hardware/spinal/tools"))
import verify_ppe_memory as v


def fixture():
    report = dict(status="passed_partial_integration", issue=5, S04_complete=False,
        claim_class="source_bound_PPE_coalescer_banked_scratch_D_L1_partial_integration",
        memory_configuration=dict(sets=16, line_bytes=32, mshrs=4, instruction_cache=False),
        limits=["synthetic fixture"], cached_clock_contract="synthetic fixture", comparisons={}, diagnostics={},
        ai_vector_epilogue_cases=[f"ai_relu_256_g{i}" for i in range(32)],
        atomic_add=dict(status="passed", S04_complete=False,
            claim_class="PPE_scalar_AMOADD_D_LS_engine_D_L1_modeled_line_service", atomic_requests=3,
            operands=[1,2,3], prior_values=[10,11,13], load_after_atomic="16", backing_after_fence="16", retired=10,
            device_negative=dict(status="passed", device_atomic_rejected_before_io=True, fault_cause=4,
                device_requests=0, cache_atomic_requests=0, lower_requests=0)))
    for mode, cases in (("legacy", v.fixtures.cases()), ("cached", v.fixtures.cases()+v.extra_cases())):
        manifest, comparisons, rows = [], [], []
        for name, code, data, settings in cases:
            code = v.fixtures.p.Code.decode(code)
            kind = settings.get("kind", 0)
            manifest.append(dict(name=name, kind=kind, opcodes=sorted({i.op for i in code.instructions})))
            for i in range(2):
                comparisons.append(dict(case=name, invocation=i, status="matched"))
                ai_relu = name.startswith("ai_relu_256_g")
                rows.append(dict(case=name, invocation=i, max_mshrs=4, max_lines=4, max_words=4,
                    stalls=1, stale=1, reorders=1, scratch_parallel=1, writebacks=1,
                    accepted_lines=2, completed_lines=2, hits=2 if ai_relu else 1,
                    misses=13 if ai_relu else 1,
                    global_words=15 if ai_relu else 2, lanes=27 if ai_relu else 16,
                    retired=16 if ai_relu else 2,
                    timeout_protocol=kind >= 3, late_service_drain=kind == 4))
        report[mode+"_manifest"] = manifest
        report["comparisons"][mode] = comparisons
        report["diagnostics"][mode] = dict(status="executed", runs=rows)
    return report


def publication():
    tests = {
        "original": (0,3,11), "actual_PPE_code_store": (0,9,(77 << 32) | 0x0c000801),
        "stale_before_publication": (0,3,11), "failed_clean_preserves_old_code": (0,3,11),
        "published_PPE_code": (0,3,77), "host_edit_stays_stale": (0,3,77), "published_host_code": (0,3,43),
        "word_local_fetch_poison": (4,1,0), "whole_line_fetch_fault": (4,0,0),
        "branch_skips_poisoned_word": (0,2,0), "offered_fetch_timeout_drain": (5,0,0),
        "accepted_fetch_timeout_drain": (5,0,0), "recovery_after_late_fault": (0,2,0)}
    return dict(status="passed", claim_class="PPE_instruction_publication_and_drain_RTL",
        runs=13, publications=9, held_ack_cycles=45, code_stores=1, failed_writebacks=1, successful_writebacks=1,
        discarded_fetches=2, faulting_instruction_line_replies=5, accepted=14, completed=14, rejected=14, request_stalls=1,
        tests=[dict(name=name, cause=c, retired=r, value=str(val)) for name,(c,r,val) in tests.items()])


def instruction_fixture():
    report = fixture()
    report.update(instruction_cache=True, claim_class="source_bound_PPE_I_D_L1_fabric_partial_integration",
                  instruction_publication=publication())
    report["data_regression_manifest"] = copy.deepcopy(report["cached_manifest"])
    report["comparisons"]["data_regression"] = copy.deepcopy(report["comparisons"]["cached"])
    report["diagnostics"]["data_regression"] = copy.deepcopy(report["diagnostics"]["cached"])
    report["diagnostics"]["data_regression"]["instruction_cache"] = False
    report["diagnostics"]["cached"]["instruction_cache"] = True
    kinds = {r["name"]:r["kind"] for r in report["cached_manifest"]}
    for r in report["diagnostics"]["cached"]["runs"]:
        fetched = int(kinds[r["case"]] != 2)
        r.update(instruction_reads=fetched, instruction_hits=0, instruction_misses=fetched, fetch_requests=fetched,
                 fabric_accepted=2, fabric_completed=2, fabric_rejected=1)
    report["delimiter_application"] = dict(status="passed", claim_class="actual_PPE_I_D_L1_32_group_task",
        groups_completed=32, input_bytes=256, accepted_lines=40, completed_lines=40, stores=256, retired=1000,
        i_misses=8, d_misses=16, output_matches_oracle=True, canaries_unchanged=True)
    report["ai_vector_application"] = dict(status="passed", kernel="ai_relu", groups_completed=32,
        input_bytes=256, accepted_lines=100, completed_lines=100, loads=608, stores=256,
        d_misses=98, output_matches_oracle=True, canaries_unchanged=True)
    return report


class PpeEvidenceTests(unittest.TestCase):
    def reject(self, mutation):
        report = fixture(); mutation(report)
        with self.assertRaises(ValueError): v.validate(report)

    def test_complete_partial_scope(self):
        v.validate(fixture())

    def test_ppe_atomic_rtl_evidence_required(self):
        self.reject(lambda r: r["atomic_add"].update(atomic_requests=2))
        self.reject(lambda r: r["atomic_add"].update(backing_after_fence="15"))

    def test_no_promotion_or_missing_matrix(self):
        self.reject(lambda r: r.update(S04_complete=True))
        self.reject(lambda r: r.update(status="running"))
        self.reject(lambda r: r["cached_manifest"].pop())
        self.reject(lambda r: r["comparisons"]["cached"].pop())
        self.reject(lambda r: r["diagnostics"]["legacy"]["runs"].append(copy.deepcopy(r["diagnostics"]["legacy"]["runs"][0])))

    def test_require_concurrency_fault_and_drain_witnesses(self):
        for field in ("max_mshrs", "max_lines", "max_words", "reorders", "scratch_parallel", "stale", "timeout_protocol", "late_service_drain"):
            self.reject(lambda r: [row.update({field: 0}) for row in r["diagnostics"]["cached"]["runs"]])

    def test_traffic_and_coalescing_not_just_final_state(self):
        self.reject(lambda r: r["diagnostics"]["cached"]["runs"][0].update(completed_lines=1))
        self.reject(lambda r: r["diagnostics"]["cached"]["runs"][0].update(hits=0))
        self.reject(lambda r: [row.update(lanes=15) for row in r["diagnostics"]["cached"]["runs"] if row["case"] == "s04_alias_s0"])

    def test_instruction_path_and_regression_identity(self):
        v.validate(instruction_fixture())
        for mutation in (
            lambda r: r["diagnostics"]["cached"].update(instruction_cache=False),
            lambda r: r["diagnostics"]["cached"]["runs"][0].update(instruction_reads=0),
            lambda r: r["diagnostics"]["cached"]["runs"][0].update(fabric_completed=1),
            lambda r: r["comparisons"]["data_regression"].pop()):
            report = instruction_fixture(); mutation(report)
            with self.assertRaises(ValueError): v.validate(report)
        for field, value in (("groups_completed", 31), ("output_matches_oracle", False), ("canaries_unchanged", False)):
            report = instruction_fixture(); report["delimiter_application"][field] = value
            with self.assertRaises(ValueError): v.validate(report)
        for field, value in (("groups_completed", 31), ("output_matches_oracle", False),
                             ("canaries_unchanged", False), ("completed_lines", 99)):
            report = instruction_fixture(); report["ai_vector_application"][field] = value
            with self.assertRaises(ValueError): v.validate(report)

    def test_publication_fault_and_late_fetch_requirements(self):
        v.validate_publication(publication())

    def test_uncached_device_path_requires_clean_identity_and_drain(self):
        report = dict(status="passed", issue=5, S04_complete=False,
            claim_class="actual_PPE_I_D_L1_clean_then_uncached_device_RTL", instruction_cache=True, device_requests=2,
            device_reads=1, device_writes=1, device_backpressure_cycles=1,
            clean_before_every_device_request=True, malformed_response_id_rejected=True,
            malformed_response_epoch_rejected=True, lower_accepted=2, lower_completed=2,
            architectural_completion=dict(status=1, cause=0, value="305419896"),
            limits=["PPE scalar AMOADD is covered separately; cross-engine atomic serialization is not established"])
        v.validate_device(report)
        for mutation in (
            lambda r: r.update(device_requests=1),
            lambda r: r.update(clean_before_every_device_request=False),
            lambda r: r.update(malformed_response_epoch_rejected=False),
            lambda r: r.update(lower_completed=1)):
            broken = copy.deepcopy(report); mutation(broken)
            with self.assertRaises(ValueError): v.validate_device(broken)

    def test_publication_failure_retry_and_drain(self):
        for field in ("failed_writebacks", "successful_writebacks", "discarded_fetches", "completed", "held_ack_cycles"):
            report = publication(); report[field] = 0
            with self.assertRaises(ValueError): v.validate_publication(report)
        report = publication(); report["tests"][4]["value"] = "11"
        with self.assertRaises(ValueError): v.validate_publication(report)

    def test_current_source_application_record_is_not_issue_completion(self):
        evidence = json.loads((Path(__file__).resolve().parents[1] / "evidence" /
            "S04-PPE-CURRENT-SOURCE-APPLICATION.json").read_text())
        self.assertEqual(evidence["status"], "passed_focused_current_source_rtl_simulation")
        self.assertFalse(evidence["S04_complete"])
        result = evidence["run_result"]
        self.assertEqual(result["groups_completed"], 32)
        self.assertEqual(result["accepted_lines"], result["completed_lines"])
        self.assertEqual(result["output_sha256"], evidence["full_output_memory_sha256"])
        self.assertEqual(result["output_sha256"],
            "75636dc4c5986fdb33923c088583a88c2e4a6c026be0bac8315f2e9f6f1cfbd7")
        self.assertTrue(any("broad PPE" in limit for limit in evidence["limits"]))


if __name__ == "__main__": unittest.main()
