#!/bin/sh
# Build the recovery's modem/WLAN bring-up tools.
#
# These are aarch64 static programs that run inside the recovery: the name
# service, the service locator, the holder that starts the modem, the WLFW
# sequence, and two small helpers.  They are built here rather than in CI
# because CI needs an account with build minutes, and the programs are small:
# a cross compiler and the sources below are the whole requirement.
#
#   CC=aarch64-linux-gnu-gcc ./scripts/build-tools.sh
#   CC=<path to aarch64-linux-android28-clang> ./scripts/build-tools.sh
#
# Sources are cloned into build/tools-src on first use.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${OUT:-$ROOT/build/tools}
SRC=${SRC:-$ROOT/build/tools-src}
CC=${CC:-aarch64-linux-gnu-gcc}
STRIP=${STRIP:-}

mkdir -p "$OUT" "$SRC"

need() {
	if [ ! -d "$SRC/$1" ]; then
		echo "== fetching $1"
		git clone --depth 1 "$2" "$SRC/$1"
	fi
}

need pd-mapper https://github.com/linux-msm/pd-mapper.git
need qrtr https://github.com/linux-msm/qrtr.git

# The phone's domain files are plain JSON; upstream's reader includes the xz
# header without using it, and pulls in a decompressor that is not needed.
mkdir -p "$OUT/fake"
echo '/* not needed: the domain files here are plain */' > "$OUT/fake/lzma.h"
echo 'int lzma_decomp(const char *file) { (void)file; return -1; }' > "$OUT/fake/lzma_decomp.c"

# The locator is patched for this phone: no remote processors are announced by
# this kernel, and the conversation with the modem is otherwise invisible.
python3 "$ROOT/scripts/patch-pd-mapper.py" "$SRC/pd-mapper"

QRTR_INC=$SRC/qrtr/include
QRTR_LIB="$SRC/qrtr/lib/qrtr.c $SRC/qrtr/lib/qmi.c $SRC/qrtr/lib/logging.c"

# shellcheck disable=SC2086
"$CC" -O2 -static -Wall -Wextra -o "$OUT/wlfwd" "$ROOT/wlfwd/wlfwd.c" $QRTR_LIB -I "$QRTR_INC"
# shellcheck disable=SC2086
"$CC" -O2 -static -Wall -o "$OUT/pdr-restart" "$ROOT/wlfwd/pdr-restart.c"
"$CC" -O2 -static -Wall -o "$OUT/modemhold" "$ROOT/wlfwd/modemhold.c"

# shellcheck disable=SC2086
"$CC" -O2 -static -Wall \
	-I "$OUT/fake" -I "$QRTR_INC" -I "$SRC/pd-mapper" \
	-o "$OUT/pd-mapper" \
	"$SRC/pd-mapper/pd-mapper.c" "$SRC/pd-mapper/assoc.c" \
	"$SRC/pd-mapper/json.c" "$SRC/pd-mapper/servreg_loc.c" \
	"$OUT/fake/lzma_decomp.c" $QRTR_LIB

# shellcheck disable=SC2086
"$CC" -O2 -static -Wall -I "$QRTR_INC" -I "$SRC/qrtr/src" \
	-o "$OUT/qrtr-ns" \
	"$SRC/qrtr/src/ns.c" "$SRC/qrtr/src/addr.c" "$SRC/qrtr/src/hash.c" \
	"$SRC/qrtr/src/map.c" "$SRC/qrtr/src/waiter.c" "$SRC/qrtr/src/util.c" \
	$SRC/qrtr/lib/qrtr.c $SRC/qrtr/lib/logging.c
# shellcheck disable=SC2086
"$CC" -O2 -static -Wall -I "$QRTR_INC" -I "$SRC/qrtr/src" \
	-o "$OUT/qrtr-lookup" \
	"$SRC/qrtr/src/lookup.c" "$SRC/qrtr/src/addr.c" "$SRC/qrtr/src/util.c" \
	$SRC/qrtr/lib/qrtr.c $SRC/qrtr/lib/logging.c

if [ -n "$STRIP" ]; then
	for f in "$OUT"/*; do
		[ -f "$f" ] && "$STRIP" --strip-all "$f" 2>/dev/null || true
	done
fi

ls -l "$OUT"
