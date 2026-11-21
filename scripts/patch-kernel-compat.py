#!/usr/bin/env python3
"""Apply narrow sdm845/WALT source compatibility fixes from observed CI errors."""
from pathlib import Path
import re
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")


def replace_once(path: str, pattern: str, replacement: str) -> None:
    file = root / path
    text = file.read_text()
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, got {count}")
    file.write_text(updated)


# This tree exposes capacity_of(), whereas its scheduler tracepoint uses cpu_capacity().
replace_once(
    "include/trace/events/sched.h",
    r"(__entry->capacity\s*=\s*)cpu_capacity\(rq->cpu\)",
    r"\1capacity_of(rq->cpu)",
)

# Reconcile this WALT function's stale cluster member and local names with the
# current sched_cluster structure. Scope edits strictly to group_will_fit().
walt = root / "kernel/sched/walt.c"
walt_text = walt.read_text()
walt_match = re.search(r"static int\s+group_will_fit\(.*?\n\}", walt_text, re.S)
if not walt_match:
    raise SystemExit("kernel/sched/walt.c: group_will_fit was not found")
walt_function = walt_match.group(0)
if walt_function.count("cluster->capacity") < 2:
    raise SystemExit("kernel/sched/walt.c: expected stale cluster capacity references")
walt_function = walt_function.replace("cluster->capacity", "cluster->max_possible_capacity")
walt_function = re.sub(r"\bmax_capacity\b", "max_possible_capacity", walt_function)
walt.write_text(walt_text[:walt_match.start()] + walt_function + walt_text[walt_match.end():])

# This WALT helper accepts an optional output pointer; this caller needs none.
replace_once(
    "kernel/sched/fair.c",
    r"(?m)(unsigned long util\s*=\s*cpu_util_freq\(cpu)\);",
    r"\1, NULL);",
)

# Current sched_cluster APIs expose is_max_capacity_cpu().
replace_once(
    "kernel/sched/boost.c",
    r"cpu_capacity\(i\)\s*!=\s*max_capacity",
    r"!is_max_capacity_cpu(i)",
)

# Upstream left the cftype initializers without the array declaration.
tune = root / "kernel/sched/tune.c"
tune_text = tune.read_text()
tune_anchor = (
    "#endif\n\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\t{\n"
    "\t\t.name = \"sched_boost_no_override\","
)
if tune_text.count(tune_anchor) != 1:
    raise SystemExit(
        "kernel/sched/tune.c: expected one cftype insertion point, "
        f"found {tune_text.count(tune_anchor)}"
    )
tune_replacement = (
    "#endif\n\n"
    "static struct cftype files[] = {\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\t{\n"
    "\t\t.name = \"sched_boost_no_override\","
)
tune.write_text(tune_text.replace(tune_anchor, tune_replacement, 1))

print("Applied scheduler tracepoint, WALT, boost, and schedtune compatibility fixes")
