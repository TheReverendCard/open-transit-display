"""Offline rollback tests with an Arduino-style dual-slot S3 flash image."""
import contextlib
import hashlib
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

import bench_flash as app


def table_bytes():
    data = b""
    for kind, sub, offset, size, label in (
        (1, 2, 0x9000, 0x5000, b"nvs"), (1, 0, 0xe000, 8192, b"otadata"),
        (0, 16, 0x10000, 0x20000, b"app0"), (0, 17, 0x30000, 0x20000, b"app1"),
    ):
        data += struct.pack("<HBBII16sI", 0x50aa, kind, sub, offset, size, label, 0)
    md5 = b"\xeb\xeb" + b"\xff"*14 + hashlib.md5(data).digest()
    return (data + md5).ljust(4096, b"\xff")


def record(seq):
    n = struct.pack("<I", seq)
    return n + b"\xff"*24 + struct.pack("<I", zlib.crc32(n, 0xffffffff))


class FakeDevice:
    def __init__(self):
        self.data = bytearray(b"\xcc" * 0x50000)
        self.data[0x8000:0x9000] = table_bytes()
        self.data[0xe000:0x10000] = (record(1).ljust(4096, b"\xff") +
                                      record(2).ljust(4096, b"\xff"))
        for offset in (0x10000, 0x30000):
            self.data[offset] = 0xe9
        self.writes = 0

    def run(self, *args):
        return "MAC:  7c:0c:5f:49:ab:cd"

    def read(self, offset, n):
        return bytes(self.data[offset:offset+n])

    def write(self, offset, data):
        self.writes += 1
        self.data[offset:offset+len(data)] = data


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        self.device = FakeDevice()
        self.initial = bytes(self.device.data)
        self.binary = b"\xe9" + b"\x35"*5130
        (self.cwd / "ClockRefreshBench.bin").write_bytes(self.binary)
        (self.cwd / "ClockRefreshBench.sha256").write_text(app.sha(self.binary))
        self.enterContextCompat(patch.object(app, "HERE", self.cwd))
        self.enterContextCompat(contextlib.redirect_stdout(io.StringIO()))

    def enterContextCompat(self, ctx):
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def run_op(self, mode, node="495F0C7C", answer=""):
        app.transfer(mode, self.device, node, self.cwd/"backups", ask=lambda _: answer)

    def test_only_selected_sectors_change_restore_exactly(self):
        self.run_op("install")
        expected = bytearray(self.initial)
        expected[0x30000:0x32000] = self.binary.ljust(8192, b"\xff")
        self.assertEqual(self.device.data, expected)
        self.run_op("install")
        self.assertEqual(self.device.writes, 1)
        self.run_op("restore")
        self.assertEqual(self.device.data, self.initial)
        self.assertEqual(len(list(self.cwd.rglob("restored-*.zip"))), 1)

    def test_interrupted_flash_recovery(self):
        def broken(offset, payload):
            self.device.data[offset:offset+300] = payload[:300]
            raise OSError("simulated disconnect")
        with patch.object(self.device, "write", broken), self.assertRaises(OSError):
            self.run_op("install")
        with self.assertRaises(ValueError):
            self.run_op("install")
        with self.assertRaises(ValueError):
            self.run_op("restore", answer="no")
        self.run_op("restore", answer="RESTORE 495F0C7C")
        self.assertEqual(self.device.data, self.initial)

    def test_wrong_board_and_damaged_image(self):
        with self.assertRaises(ValueError): self.run_op("install", "00000001")
        (self.cwd / "ClockRefreshBench.bin").write_bytes(b"\xe9wrong")
        with self.assertRaises(ValueError): self.run_op("install")
        self.assertEqual(self.device.writes, 0)

    def test_corrupt_table(self):
        self.device.data[0x8000+12] ^= 1
        with self.assertRaises(ValueError): self.run_op("install")
        self.assertEqual(self.device.writes, 0)

    def test_erased_ota_defaults_to_app0(self):
        self.device.data[0xe000:0x10000] = b"\xff" * 8192
        self.run_op("install")
        self.assertEqual(self.device.read(0x10000,len(self.binary)), self.binary)
        self.assertEqual(self.device.read(0x30000,len(self.binary)), self.initial[0x30000:0x30000+len(self.binary)])

if __name__ == "__main__":
    unittest.main()
