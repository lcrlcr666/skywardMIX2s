#!/system/bin/sh
# Show the owner's shared storage where the rest of the system expects it.
#
# Two things are missing in this recovery, and both are needed before a
# computer sees any files:
#
#   * the data partition is not mounted at boot.  init mounts what the phone's
#     table names; here /cache comes up and /data does not, so nothing can be
#     shown from it.  It is mounted here, read-write when the phone allows it
#     and read-only otherwise - the files come out in the clear either way on
#     this phone, so a computer can read them even without the credential;
#   * Android's vold binds the user's media folder onto /sdcard when a user is
#     unlocked, and Skyward does it in its own data-partition flow, which a
#     recovery never runs.  Without that binding /sdcard is an empty directory
#     in the ramdisk, which is what file transfer was offering.

DATA=/data
MEDIA=$DATA/media/0

log() { echo "shared-storage: $*" > /dev/kmsg; }

is_mounted() {
	grep -q " $1 " /proc/mounts
}

mount_data() {
	for dev in /dev/block/by-name/userdata /dev/block/by-name/data /dev/block/sda22; do
		[ -e "$dev" ] || continue
		mount -t f2fs -o rw "$dev" "$DATA" 2>/dev/null && return 0
		mount -t f2fs -o ro "$dev" "$DATA" 2>/dev/null && return 0
	done
	return 1
}

# The mounting is done first thing, without waiting for init: Skyward opens
# its MTP port about four seconds in, and a storage that appears after that is
# only offered to the computer when the file-transfer toggle is used again.
mkdir -p "$DATA"

i=0
while [ $i -lt 30 ]; do
	is_mounted "$DATA" && break
	if [ $i -gt 0 ]; then
		mount_data && log "$DATA mounted by this script"
	fi
	i=$((i + 1))
	[ $i -lt 30 ] && sleep 1
done
is_mounted "$DATA" || log "could not mount $DATA"

# The media folder can take a moment to appear behind a freshly mounted
# partition, and it is also worth a second try if the first mount was empty.
i=0
while [ $i -lt 30 ]; do
	[ -d "$MEDIA" ] && break
	i=$((i + 1))
	sleep 1
done

if [ ! -d "$MEDIA" ]; then
	log "no $MEDIA, nothing bound"
	exit 0
fi

for at in /sdcard /storage/emulated/0; do
	mkdir -p "$at" 2>/dev/null
	if mount -o bind "$MEDIA" "$at" 2>/dev/null; then
		log "$at now shows $MEDIA"
	else
		log "could not bind $at"
	fi
done

log "shared storage: $(ls "$MEDIA" 2>/dev/null | wc -l) entries, writable=$([ -w "$MEDIA" ] && echo yes || echo no)"

