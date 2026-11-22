"""App-only installer and rollback for an EE04 XIAO ESP32-S3 Plus."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
import zipfile
import zlib

HERE = Path(__file__).resolve().parent
SECTOR = 4096
TABLE = 0x8000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def slots(table):
    apps = {}
    ota = None
    for i in range(0, 3072, 32):
        entry = table[i:i + 32]
        if entry[:2] == b"\xeb\xeb":
            if hashlib.md5(table[:i]).digest() != entry[16:32]:
                raise ValueError("Partition table checksum mismatch.")
            break
        if entry[:2] != b"\xaa\x50":
            raise ValueError("Unrecognised partition table.")
        _, kind, sub, addr, size, _, flags = struct.unpack("<HBBII16sI", entry)
        if not kind and 0x10 <= sub <= 0x1f:
            if flags or addr < 0x10000 or addr % 0x10000 or size % SECTOR or not size:
                raise ValueError("Unsupported app partition.")
            apps[sub - 0x10] = (addr, size)
        if not kind and sub == 0:
            raise ValueError("This sign installer targets the Arduino OTA layout without a factory slot.")
        if kind == 1 and sub == 0:
            ota = (addr, size)
    else:
        raise ValueError("Missing partition table checksum.")
    if not apps or sorted(apps) != list(range(len(apps))) or not ota or ota[1] != 2 * SECTOR:
        raise ValueError("Unrecognised Arduino OTA layout.")
    return apps, ota[0]


def boot_slot(data, count):
    entries = []
    empty = True
    for start in (0, SECTOR):
        entry = data[start:start + 32]
        seq, state, crc = struct.unpack("<I20xII", entry)
        if entry == b"\xff"*32:
            continue
        empty = False
        if seq in (0, 0xffffffff) or crc != zlib.crc32(entry[:4], 0xffffffff):
            continue
        if state in (3, 4):  # ESP_OTA_IMG_INVALID / ABORTED
            continue
        if state not in (2, 0xffffffff):
            raise ValueError("OTA confirmation pending. Boot the normal firmware before the experiment.")
        entries.append(seq)
    if entries:
        return (max(entries) - 1) % count
    if empty:
        return 0
    raise ValueError("No valid OTA selection found.")


def find_tool():
    base = Path.home() / "AppData/Local/Arduino15/packages/esp32/tools/esptool_py"
    installed = sorted(base.glob("*/esptool.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    tool = str(installed[0]) if installed else shutil.which("esptool")
    if not tool:
        raise ValueError("Install esptool 5.x or the ESP32 Arduino board package.")
    return tool


class Device:
    def __init__(self, port, work):
        self.command = [find_tool(), "--chip", "esp32s3", "--port", port, "--baud", "460800"]
        self.work = work

    def run(self, *args, reboot=False):
        cmd = self.command + ["--after", "hard-reset" if reboot else "no-reset"] + list(args)
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        if p.returncode:
            raise ValueError(p.stdout.strip())
        return p.stdout

    def read(self, offset, count):
        out = self.work / "read.bin"
        self.run("read-flash", hex(offset), hex(count), str(out))
        data = out.read_bytes()
        if len(data) != count:
            raise ValueError("Short flash read.")
        return data

    def write(self, offset, data):
        path = self.work / "write.bin"
        path.write_bytes(data)
        self.run("write-flash", hex(offset), str(path))
        if self.read(offset, len(data)) != data:
            raise ValueError("Flash read-back differs. Keep the backup and run Restore.")


def save_backup(path, data, info):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("original.bin", data)
            z.writestr("receipt.json", json.dumps(info, indent=2))
        if load_backup(tmp) != (data, info):
            raise ValueError("Backup verification failed.")
        # A hard link publishes the completed file without replacing an earlier backup.
        os.link(tmp, path)
    finally:
        tmp.unlink()


def load_backup(path):
    with zipfile.ZipFile(path) as z:
        data = z.read("original.bin")
        info = json.loads(z.read("receipt.json"))
    if sha(data) != info["original_sha256"] or len(data) != info["length"]:
        raise ValueError("Recovery backup failed its integrity check.")
    return data, info


def transfer(mode, device, node, backup_dir, ask=input):
    output = device.run("read-mac")
    m = re.search(r"(?im)^\s*(?:base\s+)?MAC:\s*((?:[0-9a-f]{2}:){5}[0-9a-f]{2})", output)
    if not m:
        raise ValueError("Could not identify board MAC.")
    mac = bytes.fromhex(m.group(1).replace(":", ""))
    actual = f"{int.from_bytes(mac[:4], 'little'):08X}"
    if actual != node.upper():
        raise ValueError(f"Connected node {actual}, expected sign {node}. Check the COM port.")
    table = device.read(TABLE, SECTOR)
    apps, ota = slots(table)
    selected = boot_slot(device.read(ota, 2 * SECTOR), len(apps))
    offset, capacity = apps[selected]
    path = backup_dir / mac.hex() / "active-recovery.zip"
    print(f"Sign {actual}, app{selected} at {offset:#x}. Recovery file: {path}", flush=True)
    if mode == "install":
        image = (HERE / "ClockRefreshBench.bin").read_bytes()
        expected = (HERE / "ClockRefreshBench.sha256").read_text().split()[0]
        if sha(image) != expected or image[:1] != b"\xe9" or len(image) > capacity:
            raise ValueError("Bench image checksum, format or size mismatch.")
        payload = image + b"\xff" * (-len(image) % SECTOR)
        if not image or len(payload) > capacity:
            raise ValueError("Bench image exceeds selected slot.")
        current = device.read(offset, len(payload))
        if path.exists():
            original, info = load_backup(path)
            if (info["mac"], info["table_sha256"], info["offset"], info["bench_sha256"]) != (mac.hex(), sha(table), offset, sha(payload)):
                raise ValueError("Another experiment has a pending backup. Restore it first.")
            if current == payload:
                print("Bench firmware already installed.")
                return
            if current != original:
                raise ValueError("Prior installation was interrupted or the app changed. Run Restore.")
        else:
            if current == payload or current[:1] != b"\xe9":
                raise ValueError("Original bootable application could not be identified.")
            info = dict(mac=mac.hex(), offset=offset, table_sha256=sha(table), length=len(current),
                        original_sha256=sha(current), bench_sha256=sha(payload))
            save_backup(path, current, info)
        device.write(offset, payload)
        print("Bench application verified.")
    else:
        original, info = load_backup(path)
        if (info["mac"], info["table_sha256"], info["offset"]) != (mac.hex(), sha(table), offset) or len(original) > capacity:
            raise ValueError("Device, partition table or boot selection differs from the backup.")
        current = device.read(offset, len(original))
        if sha(current) not in (info["bench_sha256"], info["original_sha256"]):
            if ask("App differs from both saved images. To overwrite it with your backup, type RESTORE " + actual + ": ").strip() != "RESTORE " + actual:
                raise ValueError("Restore cancelled.")
        if current != original:
            device.write(offset, original)
        archive = path.with_name(f"restored-{time.time_ns()}.zip")
        path.rename(archive)
        print(f"Original application bytes verified. Recovery archive: {archive}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("install", "restore"))
    parser.add_argument("--node", required=True, help="eight hex digits shown by the working sign")
    parser.add_argument("--port")
    args = parser.parse_args()
    port = args.port or input("Sign COM port (close Serial Monitor first): ").strip()
    if not re.fullmatch(r"COM[1-9][0-9]*", port, flags=re.I):
        raise ValueError("Enter a Windows COM port such as COM3.")
    backup_dir = Path.home() / "Documents/OTD/backups/clock-refresh-bench"
    with tempfile.TemporaryDirectory() as temp:
        device = Device(port, Path(temp))
        transfer(args.mode, device, args.node, backup_dir)
        device.run("read-mac", reboot=True)
    print("Board restarted.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, zipfile.BadZipFile, KeyError, EOFError) as err:
        raise SystemExit(f"Stopped: {err}\nIf the board remains in download mode, press RESET.")
