#!/system/bin/sh
# Bring the modem up and keep it up, then let the protection domains be
# announced: this is the order Android's own init uses, done by hand.
#
#   1. the modem partition is mounted where ueventd looks for firmware;
#   2. qrtr-ns runs, so services have somewhere to register;
#   3. pd-mapper answers the service locator, so the modem can be told where
#      its protection domains live - up before the modem, not after it;
#   4. the modem node is held open, which is what starts the processor.
#
# Two things learned the hard way, both written down here so the next boot
# does not have to learn them again:
#
#   * the modem's restart level is SYSTEM, so a modem that faults takes the
#     whole phone with it into the installed system and the log is gone.
#     Until the bring-up is complete it is set to RELATED, so a fault leaves
#     a log instead of a reboot;
#   * nothing here kills the locator while the modem is up: the kernel's
#     locator client loses its server and the modem faults two seconds later.

FW_DIR=/firmware
STATE=/sys/bus/msm_subsys/devices/subsys0/state

log() { echo "modem-up: $*" > /dev/kmsg; }
# what the tools say goes to the same place, so one console log holds the
# whole bring-up and a failed boot can be read afterwards
start_bg() { "$@" >/dev/kmsg 2>&1 & }

log "starting"

mkdir -p "$FW_DIR" /vendor

# A fault in the modem should cost a log line, not the phone.
if [ -w /sys/bus/msm_subsys/devices/subsys0/restart_level ]; then
	echo RELATED > /sys/bus/msm_subsys/devices/subsys0/restart_level
	log "modem restart level $(cat /sys/bus/msm_subsys/devices/subsys0/restart_level)"
fi

# 1. firmware.  The modem partition is vfat and read-only here; retry in case
# it is still being scanned when this runs.
i=0
while [ $i -lt 30 ]; do
	[ -e "$FW_DIR/image/modem.mdt" ] && break
	mount -t vfat -o ro /dev/block/by-name/modem "$FW_DIR" 2>/dev/null
	i=$((i + 1))
	sleep 1
done
if [ -e "$FW_DIR/image/modem.mdt" ]; then
	log "firmware visible at $FW_DIR/image"
else
	log "no modem.mdt under $FW_DIR/image"
fi

# The vendor's own name for the same place, which the tools are written
# against, and the parameter a kernel that loads firmware directly reads.
[ -e /vendor/firmware_mnt ] || ln -s "$FW_DIR" /vendor/firmware_mnt 2>/dev/null
[ -w /sys/module/firmware_class/parameters/path ] &&
	echo -n "$FW_DIR/image" > /sys/module/firmware_class/parameters/path

# The WLAN driver goes in before the modem is started: icnss registers its
# interest in the wlan/fw protection domain as the driver loads, and the modem
# starts that domain as it boots - which is the order the installed system
# runs in, where the domain is announced about a second after the modem comes
# out of reset.  The module is 10 MB and the recovery partition has no room
# for it, so it lives on the data partition.
mkdir -p /data
if ! grep -q " /data " /proc/mounts; then
	for dev in /dev/block/by-name/userdata /dev/block/sda22; do
		[ -e "$dev" ] || continue
		mount -t f2fs -o rw "$dev" /data 2>/dev/null && break
		mount -t f2fs -o ro "$dev" /data 2>/dev/null && break
	done
fi
if [ -f /data/local/tmp/qca_cld3_wlan.ko ]; then
	insmod /data/local/tmp/qca_cld3_wlan.ko
	log "wlan module loaded, rc=$?"
else
	log "no wlan module on the data partition"
fi

# 2. the name service, before anything registers with it.  It runs with -f,
# as Android runs it: without forwarding, a lookup for a service that lives on
# another node - the modem's servreg, which is where the WLAN protection
# domain is announced from - is answered "not here" instead of being passed on.
start_bg /skyward/qrtr-ns -f
sleep 1
log "qrtr-ns started"

# 3. the locator, before the modem asks.
start_bg /skyward/pd-mapper
sleep 1
log "pd-mapper started"

# 4. the services a remote processor fetches its images and its file system
# memory from.  Android runs both: its QRTR name service carries ten TFTP
# endpoints and a "Remote file system service", and neither exists here.
# tqftpserv reads from /lib/firmware, so the modem partition is made visible
# there.
mkdir -p /lib
[ -e /lib/firmware ] || ln -s "$FW_DIR/image" /lib/firmware
start_bg /skyward/tqftpserv
sleep 1
log "tqftpserv started"
# The modem's file system: RMTFS, serving the EFS partitions.  It finds them
# by partition label, which this recovery's ueventd does not create, so the
# links are made here.  Without it the modem asks for modem_fs1, is refused,
# and faults as it boots.
mkdir -p /dev/disk/by-partlabel
for n in modemst1 modemst2 fsg fsc; do
	[ -e "/dev/block/by-name/$n" ] && ln -sf "/dev/block/by-name/$n" "/dev/disk/by-partlabel/$n"
done
start_bg /skyward/rmtfs -P
sleep 1
log "rmtfs started with the EFS partitions"

# 5. the modem itself.
start_bg /skyward/modemhold

# Stay the service's main process and report the modem's state as it settles.
# wlfwd is not started from here: it is a step to run by hand, when the modem
# is up and its WLFW service is actually there.
last=""
i=0
while [ $i -lt 30 ]; do
	now="$(cat $STATE 2>/dev/null)"
	if [ "$now" != "$last" ]; then
		log "modem state $now"
		last="$now"
	fi
	i=$((i + 1))
	sleep 1
done

log "settled at $(cat $STATE 2>/dev/null)"
while :; do sleep 3600; done



