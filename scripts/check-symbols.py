#!/usr/bin/env python3
"""Check that a program built for a phone asks its libraries only for what they have.

Usage: check-symbols.py <program> <stock recovery image> [more programs...]

The program is linked against the NDK's libraries for one API level; the phone
runs the libraries of its own stock recovery. A symbol the NDK has and the
phone's do not makes the program fail to load, before anything of it runs, so
this reads both and names what is missing.
"""

import gzip
import struct
import sys

CPIO_MAGIC = (b"070701", b"070702")
WANTED = ("libc.so", "liblog.so", "libm.so", "libdl.so", "libstdc++.so", "libc++_shared.so",
          "libandroid.so", "libutils.so", "libcutils.so")


def parse_boot(buf):
    if buf[:8] != b"ANDROID!":
        raise SystemExit("not a boot image")
    kernel_size, _, ramdisk_size, _, _, _, _, page_size, version, _ = struct.unpack_from("<10I", buf, 8)
    if version not in (0, 1, 2):
        raise SystemExit(f"header version {version} is not 0 to 2")
    at = page_size
    at += (kernel_size + page_size - 1) // page_size * page_size
    return buf[at:at + ramdisk_size], page_size


def unpack_ramdisk(ramdisk):
    if ramdisk[:2] == b"\x1f\x8b":
        return gzip.decompress(ramdisk)
    return ramdisk


def cpio_entries(cpio):
    rest = cpio
    while True:
        if rest[:6] not in CPIO_MAGIC:
            return
        fields = [int(rest[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
        size, namesize = fields[6], fields[11]
        name = rest[110:110 + namesize - 1].decode(errors="replace").lstrip("./")
        data_at = 110 + namesize
        data = rest[data_at:data_at + size]
        rest = rest[(data_at + size + 3) // 4 * 4:]
        if name == "TRAILER!!!":
            return
        yield name, data


def elf_symbols(blob):
    """(defined, undefined) name sets of an ELF64 little-endian file."""
    if blob[:4] != b"\x7fELF" or blob[4] != 2 or blob[5] != 1:
        return set(), set()
    e_shoff, = struct.unpack_from("<Q", blob, 0x28)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", blob, 0x3A)
    sections = []
    for i in range(e_shnum):
        base = e_shoff + i * e_shentsize
        sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, sh_align, sh_entsize = \
            struct.unpack_from("<IIQQQQIIQQ", blob, base)
        sections.append((sh_name, sh_type, sh_offset, sh_size, sh_link, sh_entsize))
    defined, undefined = set(), set()
    for sh_name, sh_type, sh_offset, sh_size, sh_link, sh_entsize in sections:
        if sh_type != 11:  # SHT_DYNSYM
            continue
        str_off, str_size = sections[sh_link][2], sections[sh_link][3]
        strs = blob[str_off:str_off + str_size]
        for off in range(sh_offset, sh_offset + sh_size, sh_entsize or 24):
            st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from("<IBBHQQ", blob, off)
            if st_name == 0:
                continue
            end = strs.find(b"\0", st_name)
            name = strs[st_name:end].decode(errors="replace")
            if st_shndx == 0:
                undefined.add(name)
            else:
                defined.add(name)
    return defined, undefined


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    stock = sys.argv[2]
    programs = [sys.argv[1]] + sys.argv[3:]

    with open(stock, "rb") as f:
        ramdisk, _ = parse_boot(f.read())
    entries = dict(cpio_entries(unpack_ramdisk(ramdisk)))
    libs = {}
    for name, data in entries.items():
        base = name.rsplit("/", 1)[-1]
        if base in WANTED and data[:4] == b"\x7fELF":
            got, _ = elf_symbols(data)
            libs[base] = got
            print(f"library in the stock recovery: {name} ({len(got)} defined symbols)")
    if not libs:
        raise SystemExit("the stock recovery ramdisk holds none of the libraries the program needs")

    provided = set().union(*libs.values())
    missing_any = False
    for path in programs:
        with open(path, "rb") as f:
            blob = f.read()
        defined, undefined = elf_symbols(blob)
        missing = sorted(undefined - provided)
        print(f"{path}: {len(undefined)} symbols imported, {len(missing)} the stock libraries lack")
        for name in missing:
            missing_any = True
            print(f"  missing: {name}")
    if missing_any:
        raise SystemExit("the phone's libraries would fail to load this program")
    print("ok")


if __name__ == "__main__":
    main()
