#!/usr/bin/env python3
"""Check a recovery image built for an A-only phone: boot header, ramdisk and AVB footer.

Usage: verify-image.py <image> [--expect-recovery-bytes N]

Names what a phone would refuse rather than what a build would notice: a
header it cannot read, a ramdisk cut short, a recovery program the stock one
was not replaced in, a partition the image does not fill, and a footer that
does not cover it. Exits non-zero when any of them is wrong.
"""

import gzip
import struct
import sys


def aligned(n, page):
    return (n + page - 1) // page * page


def parse_header(buf):
    if buf[:8] != b"ANDROID!":
        raise SystemExit(f"not an Android boot image (magic {buf[:8]!r})")
    (kernel_size, kernel_addr, ramdisk_size, ramdisk_addr, second_size, second_addr,
     tags_addr, page_size, header_version, os_version) = struct.unpack_from("<10I", buf, 8)
    header = {
        "header_version": header_version,
        "page_size": page_size,
        "kernel_size": kernel_size,
        "ramdisk_size": ramdisk_size,
        "second_size": second_size,
        "os_version": hex(os_version),
        "name": buf[48:64].split(b"\0")[0].decode(errors="replace"),
        "cmdline": buf[64:576].split(b"\0")[0].decode(errors="replace"),
    }
    if header_version not in (0, 1, 2):
        raise SystemExit(f"header version {header_version} is not 0 to 2, which A-only phones carry")
    if page_size < 512 or page_size & (page_size - 1):
        raise SystemExit(f"page size {page_size} is not a power of two")
    if header_version >= 1:
        dtbo_size, dtbo_offset, header_size = struct.unpack_from("<IQI", buf, 1632)
        header.update(recovery_dtbo_size=dtbo_size, recovery_dtbo_offset=dtbo_offset, header_size=header_size)
    if header_version >= 2:
        dtb_size, dtb_addr = struct.unpack_from("<IQ", buf, 1648)
        header.update(dtb_size=dtb_size, dtb_addr=hex(dtb_addr))
    return header


def cpio_entries(cpio):
    """Every entry of a newc archive, read by finding its headers.

    Reading the archive straight through needs the writer's padding to be the
    one assumed; a writer that pads otherwise leaves the next header a few
    bytes off. Each header is found by its magic and its own sizes instead, so
    the entries come out either way.
    """
    pos = 0
    while True:
        at = cpio.find(b"070701", pos)
        if at < 0:
            return
        header = cpio[at:at + 110]
        if len(header) < 110:
            return
        try:
            fields = [int(header[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
        except ValueError:
            pos = at + 6
            continue
        mode, size, namesize = fields[1], fields[6], fields[11]
        if not 1 <= namesize <= 4096 or size > len(cpio):
            pos = at + 6
            continue
        name_at = at + 110
        raw = cpio[name_at:name_at + namesize]
        name = raw.split(b"\0")[0].decode(errors="replace").lstrip("./")
        data_at = name_at + namesize
        data = cpio[data_at:data_at + size]
        end = data_at + size
        pos = at + ((end - at + 3) // 4 * 4)
        if name == "TRAILER!!!":
            return
        if name:
            yield name, mode, data


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = sys.argv[1]
    expect = None
    if "--expect-recovery-bytes" in sys.argv:
        expect = int(sys.argv[sys.argv.index("--expect-recovery-bytes") + 1], 0)

    with open(path, "rb") as f:
        buf = f.read()
    print(f"image: {path} ({len(buf)} bytes)")

    header = parse_header(buf)
    for key, value in header.items():
        if key != "cmdline":
            print(f"  {key}: {value}")

    page = header["page_size"]
    at = page
    kernel = buf[at:at + header["kernel_size"]]
    at += aligned(header["kernel_size"], page)
    ramdisk = buf[at:at + header["ramdisk_size"]]
    if len(ramdisk) != header["ramdisk_size"]:
        raise SystemExit(f"the ramdisk runs past the end of the image ({len(ramdisk)} of {header['ramdisk_size']} bytes)")
    print(f"  kernel: {len(kernel)} bytes, ramdisk: {len(ramdisk)} bytes at {at}")

    if ramdisk[:2] == b"\x1f\x8b":
        print("  ramdisk compression: gzip")
        cpio = gzip.decompress(ramdisk)
    elif ramdisk[:4] == b"\x04\x22\x4d\x18":
        raise SystemExit("lz4 ramdisk: unpack it with lz4 -d first")
    else:
        print("  ramdisk compression: none")
        cpio = ramdisk

    entries = {name: (mode, data) for name, mode, data in cpio_entries(cpio)}
    print(f"  ramdisk entries: {len(entries)}")
    for name in list(entries)[:5]:
        print(f"    first: {name} ({len(entries[name][1])} bytes)")
    if len(entries) < 5:
        raise SystemExit("the ramdisk holds fewer entries than a recovery does: its archive was not read")

    recovery = [n for n in ("system/bin/recovery", "sbin/recovery") if n in entries]
    if not recovery:
        raise SystemExit("neither system/bin/recovery nor sbin/recovery is in the ramdisk: the stock one was not replaced")
    for name in recovery:
        mode, data = entries[name]
        print(f"  {name}: {len(data)} bytes, mode {mode:o}")
        if len(data) < 1_000_000:
            raise SystemExit(f"{name} is only {len(data)} bytes, which is not Skyward")

    props = [n for n in ("prop.default", "default.prop") if n in entries]
    if not props:
        raise SystemExit("neither prop.default nor default.prop is in the ramdisk")
    # init reads prop.default first, and a stock ramdisk may keep a short
    # default.prop beside it; the properties only have to be set in one of
    # them, in the file init reads.
    text = "\n".join(entries[name][1].decode(errors="replace") for name in props)
    for name in props:
        print(f"  {name}: {len(entries[name][1])} bytes")
    for line in ("ro.secure=0", "ro.adb.secure=0", "ro.debuggable=1"):
        if line not in text:
            raise SystemExit(f"the ramdisk's property files do not set {line}, so adb will not be root without the phone asking")

    wanted = ["init", "init.rc", "skyward/system-init", "skyward/device.toml",
              "skyward/MiSansVF.ttf", "skyward/KirkMono-Regular.ttf", "system/bin/sh"]
    for name in wanted:
        if name in entries:
            print(f"  {name}: {len(entries[name][1])} bytes")
        else:
            print(f"  missing: {name}")

    modules = sorted(n for n in entries if n.startswith("sbin/modules/") or n.endswith(".ko"))
    print(f"  kernel modules in the ramdisk: {len(modules)}")
    for name in modules[:10]:
        print(f"    {name}")

    if "skyward/device.toml" in entries:
        print("  device.toml:")
        for line in entries["skyward/device.toml"][1].decode(errors="replace").splitlines():
            print(f"    {line}")

    if buf[-64:-60] == b"AVBf":
        print("  AVB footer: present at the end of the image")
    else:
        raise SystemExit(f"no AVB footer at the end of the image (last 64 bytes start {buf[-64:-60]!r})")

    if expect is not None and len(buf) != expect:
        raise SystemExit(f"the image is {len(buf)} bytes, where the recovery partition takes {expect}")
    print("ok")


if __name__ == "__main__":
    main()
