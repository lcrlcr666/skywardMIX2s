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
        at = rest.find(b"070701")
        if at < 0:
            return
        header = rest[at:at + 110]
        if len(header) < 110:
            return
        try:
            fields = [int(header[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
        except ValueError:
            rest = rest[at + 6:]
            continue
        size, namesize = fields[6], fields[11]
        if not 1 <= namesize <= 4096 or size > len(rest):
            rest = rest[at + 6:]
            continue
        name_at = at + 110
        name = rest[name_at:name_at + namesize].split(b"\0")[0].decode(errors="replace").lstrip("./")
        # Name and data are padded to four bytes from the start of the archive.
        data_at = name_at + namesize
        data_at += (4 - data_at % 4) % 4
        data = rest[data_at:data_at + size]
        end = data_at + size
        end += (4 - end % 4) % 4
        rest = rest[end:]
        if name == "TRAILER!!!":
            return
        if name:
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
    print(f"the stock recovery ramdisk holds {len(entries)} entries")
    libs = {}
    for name, data in entries.items():
        if data[:4] != b"\x7fELF":
            continue
        base = name.rsplit("/", 1)[-1]
        if ".so" not in base:
            continue
        got, _ = elf_symbols(data)
        if got:
            libs[name] = got
    for name in sorted(libs):
        print(f"library in the stock recovery: {name} ({len(libs[name])} defined symbols)")
    if not libs:
        # Whatever the layout, name what is there, so the next run can look
        # in the right place instead of guessing again.
        for name in list(entries)[:20]:
            print(f"  entry: {name} ({len(entries[name])} bytes)")
        raise SystemExit("the stock recovery ramdisk holds no shared library this could check against")

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
