import struct
import unittest
import task_abi as abi


class TaskAbiTests(unittest.TestCase):
    def test_wire_layout(self):
        self.assertEqual(abi.WIRE.size, 128)
        expected = {"task_id": 8, "engine_class": 24, "domain_mask": 28,
                    "code_handle": 32, "argument_address": 40, "argument_bytes": 48,
                    "capability_set": 56, "dependencies_address": 64, "dependency_count": 72,
                    "priority": 76, "completion_cookie": 80, "budget_ticks": 88,
                    "group_count": 96, "waves_per_group": 100, "logical_width": 102,
                    "scratch_bytes_per_group": 104, "address_space": 112,
                    "address_generation": 116, "reserved": 120}
        for name, offset in expected.items(): self.assertEqual(abi.OFFSETS[name], offset)

    def test_roundtrip_and_endian(self):
        d = abi.descriptor(task_id=0x0102030405060708)
        raw = abi.pack(d)
        self.assertEqual(raw[8:16], bytes.fromhex("0807060504030201"))
        self.assertEqual(abi.unpack(raw), d)

    def test_reject_versions_and_reserved(self):
        for update in ({"major": 1}, {"minor": 2}, {"bytes": 64}, {"kind": 2}, {"flags": 1}, {"reserved": 1}):
            with self.subTest(update=update), self.assertRaises(ValueError): abi.descriptor(**update)

    def test_reject_integer_widths(self):
        for name, kind in abi.FIELDS:
            for value in (-1, 1 << (struct.calcsize(kind) * 8), True):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    abi.descriptor(**{name: value})

    def test_reject_geometry(self):
        for update in ({"engine_class": 3}, {"logical_width": 8}, {"domain_mask": 16},
                       {"domain_mask": 0}, {"group_count": 0}, {"engine_class": 2, "logical_width": 65}):
            with self.subTest(update=update), self.assertRaises(ValueError): abi.descriptor(**update)

    def test_ranges(self):
        abi.descriptor(argument_address=(1 << 64) - 8, argument_bytes=8)
        with self.assertRaises(ValueError): abi.descriptor(argument_address=(1 << 64) - 8, argument_bytes=9)
        with self.assertRaises(ValueError): abi.descriptor(dependencies_address=(1 << 64) - 16, dependency_count=2)

    def test_dependencies(self):
        abi.descriptor(dependencies_address=16, dependency_count=8)
        for update in ({"dependency_count": 1}, {"dependencies_address": 16},
                       {"dependencies_address": 17, "dependency_count": 1},
                       {"dependencies_address": 16, "dependency_count": 9}, {"parent_id": 1}):
            with self.assertRaises(ValueError): abi.descriptor(**update)

    def test_short_long_and_unknown_field(self):
        for size in (0, 127, 129):
            with self.assertRaises(ValueError): abi.unpack(bytes(size))
        with self.assertRaises(ValueError): abi.descriptor(unknown=1)

    def test_initial_profile(self):
        abi.validate_initial_profile(abi.descriptor())
        abi.validate_initial_profile(abi.descriptor(engine_class=2, logical_width=8, scratch_bytes_per_group=4096))
        for update in ({"address_space": 1}, {"domain_mask": 3}, {"parent_id": 2},
                       {"engine_class": 2, "logical_width": 16},
                       {"engine_class": 2, "logical_width": 8, "scratch_bytes_per_group": 4112}):
            with self.assertRaises(ValueError): abi.validate_initial_profile(abi.descriptor(**update))

    def test_completion_layout(self):
        raw = abi.completion_pack(status=1, task_id=7, sequence=42, value=19, engine_id=0x10000)
        self.assertEqual(len(raw), 64)
        self.assertEqual(struct.unpack_from("<QQQ", raw, 8), (7, 42, 19))
        self.assertEqual(struct.unpack_from("<I", raw, 52)[0], 0x10000)
        with self.assertRaises(ValueError): abi.completion_pack(status=0)

    def test_scratch_reservation_overflow(self):
        with self.assertRaises(ValueError):
            abi.descriptor(engine_class=2, logical_width=8, group_count=2,
                           scratch_bytes_per_group=1 << 63)

    def test_completion_roundtrip_and_rejections(self):
        for fields in ({"status": 1, "engine_id": 0x10000},
                       {"status": 2, "engine_id": 0x20000, "cause": 3, "fault_lane_mask": 4},
                       {"status": 3}, {"status": 4, "cause": 8}, {"status": 5, "cause": 9}):
            raw = abi.completion_pack(task_id=7, sequence=23, **fields)
            self.assertEqual(abi.completion_pack(**abi.completion_unpack(raw)), raw)
        for fields in ({"status": 1}, {"status": 1, "engine_id": 0x10000, "cause": 1},
                       {"status": 2, "engine_id": 0x10000}, {"status": 2, "engine_id": 0x10000, "cause": 3, "fault_lane_mask": 1},
                       {"status": 4, "engine_id": 0x10000, "cause": 8}, {"status": 5, "cause": 8},
                       {"status": 3, "engine_id": 3}, {"status": 3, "engine_id": 0x30000},
                       {"status": 3, "cause": 10}, {"status": 3, "fault_pc": 4}):
            with self.subTest(fields=fields), self.assertRaises(ValueError): abi.completion_pack(**fields)
        for size in (0, 63, 65):
            with self.assertRaises(ValueError): abi.completion_unpack(bytes(size))

    def test_completion_field_widths(self):
        for name, kind in abi.COMPLETION_FIELDS:
            for value in (-1, 1 << (struct.calcsize(kind) * 8), True):
                fields = {"status": 3, name: value}
                with self.subTest(name=name, value=value), self.assertRaises(ValueError): abi.completion_pack(**fields)


if __name__ == "__main__": unittest.main()
