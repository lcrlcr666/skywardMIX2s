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
    """Give every *_CPU_MASK integer symbol a default of zero."""
    lines = text.split("\n")
    out = []
    in_mask = False
    for line in lines:
        if re.match(r"config .*_CPU_MASK\s*$", line):
            in_mask = True
            out.append(line)
            continue
        if in_mask and line.startswith("config "):
            in_mask = False
        if in_mask and re.match(r"\tint ", line):
            out.append(line)
            out.append("\tdefault 0")
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


patch("arch/arm64/Kconfig", masks)
patch("kernel/sched/sched.h", guard_freq)
for extra in root.glob("arch/*/Kconfig"):
    patch(str(extra.relative_to(root)), masks)

print("patched:", ", ".join(changed) if changed else "nothing to do")
