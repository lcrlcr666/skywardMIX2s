#!/usr/bin/env python3
"""Apply narrow sdm845 WALT compatibility edits required by this kernel build."""
from pathlib import Path
import re
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")


def replace_once(path: str, pattern: str, replacement: str, expected: int = 1) -> None:
    file = root / path
    text = file.read_text()
    updated, count = re.subn(pattern, replacement, text, count=expected)
    if count != expected:
        raise SystemExit(f"{path}: expected {expected} replacements, got {count}")
    file.write_text(updated)


# The tracepoint names cpu_capacity(), but this WALT tree provides capacity_of().
replace_once(
    "include/trace/events/sched.h",
    r"(__entry->capacity\s*=\s*)cpu_capacity\(rq->cpu\)",
    r"\1capacity_of(rq->cpu)",
)

# This cluster-selection code was left with member names from a different WALT
# revision. Keep the predicate and use this tree's max_possible_capacity field.
walt = root / "kernel/sched/walt.c"
text = walt.read_text()
match = re.search(r"static int\s+group_will_fit\(.*?\n\}", text, re.S)
if not match:
    raise SystemExit("kernel/sched/walt.c: group_will_fit was not found")
function = match.group(0)
capacity_refs = function.count("cluster->capacity")
max_refs = len(re.findall(r"\\bmax_capacity\\b", function))
if capacity_refs not in (2, 3, 4) or max_refs not in (0, 1):
    raise SystemExit("kernel/sched/walt.c: unexpected group_will_fit body")
function = function.replace("cluster->capacity", "cluster->max_possible_capacity")
function = re.sub(r"\bmax_capacity\b", "max_possible_capacity", function)
walt.write_text(text[:match.start()] + function + text[match.end():])

# boosted_cpu_util does not need the optional WALT diagnostic output structure.
replace_once(
    "kernel/sched/fair.c",
    r"(?m)(unsigned long util\s*=\s*cpu_util_freq\(cpu)\);",
    r"\1, NULL);",
)

# boost_kick_cpus should kick non-maximum-capacity CPUs. The newer WALT tree
# exposes that decision directly instead of cpu_capacity()/max_capacity.
replace_once(
    "kernel/sched/boost.c",
    r"cpu_capacity\(i\)\s*!=\s*max_capacity",
    r"!is_max_capacity_cpu(i)",
)

print("Applied scheduler tracepoint and WALT compatibility patches")
