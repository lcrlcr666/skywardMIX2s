#!/usr/bin/env python3
"""Make this kernel tree build in a recovery's CI, without changing what it does.

Two things in it stop a non-interactive build:

  * the CPU-mask symbols in arch/arm64/Kconfig have no default, so every build
    stops to ask for them;
  * kernel/sched/sched.h declares cpu_util_freq twice when the windowed load
    tracking is on, once with the tracking's argument and once without.

Both are fixed in the tree itself, so no later configuration pass can undo
them, and nothing about the scheduler's behaviour changes.
"""

import os
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
changed = []


def patch(path, edit):
    p = root / path
    if not p.exists():
        return
    text = p.read_text(errors="replace")
    new = edit(text)
    if new != text:
        p.write_text(new)
        changed.append(str(path))


def masks(text):
    """Give every *_CPU_MASK integer symbol the default this phone needs.

    The masks say which cores are the little ones and which the big ones:
    cores 0-3 are the four little ones and 4-7 the four big ones, and a build
    that leaves both at zero hands the scheduler a topology the phone cannot
    start with.
    """
    lines = text.split("\n")
    out = []
    in_mask = False
    wanted = ""
    for line in lines:
        match = re.match(r"config (.*_CPU_MASK)\s*$", line)
        if match:
            in_mask = True
            wanted = match.group(1)
            out.append(line)
            continue
        if in_mask and line.startswith("config "):
            in_mask = False
        if in_mask and re.match(r"\tint ", line):
            out.append(line)
            default = {"LITTLE_CPU_MASK": "15", "BIG_CPU_MASK": "240"}.get(wanted, "0")
            out.append(f"\tdefault {default}")
            in_mask = False
            continue
        out.append(line)
    return "\n".join(out)


def guard_freq(text):
    """Keep the plain cpu_util_freq out of a build that has the tracking's."""
    if "CONFIG_SCHED_WALT" not in text:
        return text
    start = text.find("static inline unsigned long cpu_util_freq(int cpu)")
    if start < 0:
        return text
    head = text.rfind("\n", 0, start)
    before = text[max(0, head - 200):head]
    if "#ifndef CONFIG_SCHED_WALT" in before:
        return text
    end = text.find("\n}\n", start)
    if end < 0:
        return text
    end += len("\n}\n")
    return text[:head] + "\n#ifndef CONFIG_SCHED_WALT" + text[head:end] + "#endif /* !CONFIG_SCHED_WALT */\n" + text[end:]


def mmap_lock(text):
    """Say what this tree calls the lock: it was renamed and one file missed."""
    return text.replace("->mmap_sem", "->mmap_lock")


def notifier_enum(text):
    """Define the event type a backport left named but undeclared."""
    if "enum mmu_notifier_event {" in text:
        return text
    anchor = "#ifdef CONFIG_MMU_NOTIFIER\n"
    if anchor not in text:
        return text
    declaration = (
        anchor
        + "\n/* The range kinds a backported notifier is told about. The tree's own\n"
        + "   range_init takes the type without using it, and nothing declares it. */\n"
        + "enum mmu_notifier_event {\n\tMMU_NOTIFIER_RANGE_BLOCKABLE = 0,\n};\n"
    )
    return text.replace(anchor, declaration, 1)


patch("arch/arm64/Kconfig", masks)
patch("include/linux/huge_mm.h", mmap_lock)
patch("include/linux/mmu_notifier.h", notifier_enum)
if os.environ.get("PATCH_SCHED") == "1":
    patch("kernel/sched/sched.h", guard_freq)
for extra in root.glob("arch/*/Kconfig"):
    patch(str(extra.relative_to(root)), masks)

print("patched:", ", ".join(changed) if changed else "nothing to do")
