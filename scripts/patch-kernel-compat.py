#!/usr/bin/env python3
"""Apply the narrow source fixes this kernel build needs, each proven by a CI log.

Every edit is anchored on text that exists in the tree today and is refused
(raising SystemExit) when the anchor is missing or appears more than once, so a
build fails loudly at configuration instead of compiling the wrong thing.
"""
from pathlib import Path
import re
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")


def read(path):
    return (root / path).read_text()


def write(path, text):
    (root / path).write_text(text)


def replace_once(path, pattern, replacement, why):
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"{path}: {why} (found {count} matches)")
    write(path, updated)


# 1. The scheduler tracepoint names cpu_capacity(); this tree exposes capacity_of().
replace_once(
    "include/trace/events/sched.h",
    r"(__entry->capacity\s*=\s*)cpu_capacity\(rq->cpu\)",
    r"\1capacity_of(rq->cpu)",
    "expected one cpu_capacity() call in the sched tracepoint",
)

# 2. group_will_fit() still uses a cluster member and a local from another WALT
#    revision; the current sched_cluster carries max_possible_capacity instead.
walt = "kernel/sched/walt.c"
walt_text = read(walt)
walt_match = re.search(r"static int\s+group_will_fit\(.*?\n\}", walt_text, re.S)
if not walt_match:
    raise SystemExit(f"{walt}: group_will_fit was not found")
walt_function = walt_match.group(0)
if walt_function.count("cluster->capacity") == 0:
    raise SystemExit(f"{walt}: no stale cluster->capacity reference to fix")
walt_function = walt_function.replace(
    "cluster->capacity", "cluster->max_possible_capacity"
)
walt_function = re.sub(r"\bmax_capacity\b", "max_possible_capacity", walt_function)
write(
    walt,
    walt_text[: walt_match.start()] + walt_function + walt_text[walt_match.end():],
)

# 3. cpu_util_freq() takes an optional WALT load-out pointer; this caller has none.
replace_once(
    "kernel/sched/fair.c",
    r"(?m)(unsigned long util\s*=\s*cpu_util_freq\(cpu)\);",
    r"\1, NULL);",
    "expected one single-argument cpu_util_freq() call",
)

# 4. boost_kick_cpus() should skip the biggest CPUs; use the current predicate.
replace_once(
    "kernel/sched/boost.c",
    r"cpu_capacity\(i\)\s*!=\s*max_capacity",
    r"!is_max_capacity_cpu(i)",
    "expected one legacy cpu_capacity()/max_capacity comparison",
)

# 5. This tree's schedtune cftype initializers were left without their array
#    declaration, and the write wrappers they name exist only under
#    CONFIG_STUNE_ASSIST. Declare the array and give the whole body that guard.
tune = "kernel/sched/tune.c"
tune_text = read(tune)
array_anchor = "#endif\n\n#ifdef CONFIG_SCHED_WALT\n\t{\n\t\t.name = \"sched_boost_no_override\","
if tune_text.count(array_anchor) != 1:
    raise SystemExit(
        f"{tune}: expected one cftype insertion point, "
        f"found {tune_text.count(array_anchor)}"
    )
tune_text = tune_text.replace(
    array_anchor,
    "#endif\n\nstatic struct cftype files[] = {\n#ifdef CONFIG_STUNE_ASSIST\n"
    "#ifdef CONFIG_SCHED_WALT\n\t{\n\t\t.name = \"sched_boost_no_override\",",
    1,
)
tail_anchor = "\t\t.write_u64 = prefer_idle_write_wrapper,\n\t},\n"
if tune_text.count(tail_anchor) != 1:
    raise SystemExit(
        f"{tune}: expected one prefer_idle cftype entry, "
        f"found {tune_text.count(tail_anchor)}"
    )
tune_text = tune_text.replace(
    tail_anchor, tail_anchor + "#endif /* CONFIG_STUNE_ASSIST */\n", 1
)
write(tune, tune_text)

# 6. The WALT branch of sugov_get_util() calls arch_scale_cpu_capacity() with one
#    argument and stune_util(), neither of which exists in this tree (they came
#    from a newer generation). The generic implementation right below it is the
#    one this tree supports, so drop the WALT variant and keep that one.
schedutil = "kernel/sched/cpufreq_schedutil.c"
schedutil_text = read(schedutil)
walt_variant = re.search(
    r"#ifdef CONFIG_SCHED_WALT\n"
    r"static unsigned long sugov_get_util\(.*?"
    r"#else\n"
    r"(static unsigned long sugov_get_util\(.*?\n\})\n"
    r"#endif\n",
    schedutil_text,
    re.S,
)
if not walt_variant:
    raise SystemExit(
        f"{schedutil}: expected the WALT sugov_get_util variant, its #else and #endif"
    )
if "stune_util(" not in walt_variant.group(0):
    raise SystemExit(f"{schedutil}: the matched block is not the WALT variant")
write(
    schedutil,
    schedutil_text[: walt_variant.start()]
    + walt_variant.group(1)
    + "\n"
    + schedutil_text[walt_variant.end():],
)

print("Applied tracepoint, WALT, boost, schedtune and schedutil compatibility fixes")