# The modem is up in the recovery, and its WLAN protection domain is announced

Written 2026-11-19, after a night of boots. Everything below was observed on
the phone, not inferred.

## Where this leaves the work

| Layer | State |
| --- | --- |
| modem processor started at boot, in the recovery | ✅ |
| QRTR name service (`qrtr-ns`) | ✅ |
| service locator answering (`pd-mapper`), `wlan/fw` -> 1 domain | ✅ |
| WLAN driver loads, `/dev/wlan` appears | ✅ |
| **WLFW service `0x45` published by the firmware** | ❌ this is the gap |
| `echo ON > /dev/wlan` | ❌ "FW is in bad state, state: 0x4180", then `Timed-out!!` |

The kernel side is finished: `icnss` is exactly where it should be, waiting
for the firmware to publish 0x45. What has not happened is the firmware
starting.

## The bring-up, in the order that works

```
mount modem partition at /firmware     # ueventd looks there for modem.mdt
/skyward/qrtr-ns &                     # name service, first
/skyward/pd-mapper &                   # locator, BEFORE the modem
/skyward/modemhold &                   # the open that starts the processor
```

Log of a boot that worked (`dmesg`, seconds after init):

```
 2.578798 modem-up: starting
 2.661326 modem-up: modem restart level RELATED
 3.747557 modem-up: firmware visible at /firmware/image
 4.833992 modem-up: qrtr-ns started
 4.840042 servloc: service_locator_new_server: Connection established with the Service locator
 4.840054 servloc: init_service_locator: Service locator initialized
 4.840171 [PD-MAPPER] wlan/fw -> 1 domain(s)
 5.877443 modem-up: pd-mapper started
 5.924486 modem-up: modem state OFFLINING
 7.448712 modemhold: modem opened, holding
 8.097480 modem-up: modem state ONLINE
```

Before this the modem could not be started at all in the recovery, and the
reason was none of the things earlier thinking blamed: it was that
`modem.mdt` was not on any partition ueventd searches. The kernel's error,
`Failed to locate modem.mdt`, says as much once the code path is read:

* `subsys_device_open()` -> `subsystem_get_with_fwname()` -> `subsys_start()`
  -> `pil-q6v5-mss` -> `request_firmware("modem.mdt")`;
* the kernel asks **ueventd** (user helper), and ueventd only searches
  `/etc/firmware`, `/odm/firmware`, `/vendor/firmware`, `/firmware/image`;
* the file lives on the `modem` partition, which nothing mounted.

So mounting it at `/firmware` is the whole fix for the modem. The
`OFFLINING`-forever state that the handoff blamed is a *consequence*: a
failed get leaves the state machine where it was, and nothing settles it.

## What is still missing, and what would fix it

The WLAN processor (WCNSS) is running — its DIAG channels appear on the name
service — but the WLFW service is not published, so:

* `qrtr-lookup 69` → nothing (`0x45 = 69`);
* `echo ON > /dev/wlan` → `icnss: FW is in bad state, state: 0x4180` and
  `Timed-out!!` from the driver;
* `/tmp/pdr-restart 0 1 msm/modem/wlan_pd` → `result 1 error 9`
  (`QMI_ERR_NOT_SUPPORTED`): the modem's servreg will not restart that
  domain from here either.

`icnss` on this kernel does not boot WCNSS itself: there is no
`subsystem_get("wcnss")` call in it. It waits. In an installed system what
turns the domain on is `/vendor/bin/cnss-daemon` (see the README's earlier
sections) — the closed daemon that needs Android 16's runtime and init
environment. That is still the piece to solve, but it is now the *only*
piece, and it is a userspace problem with a running modem underneath it,
rather than a kernel-configuration problem.

## Things that cost time, written down so they are not paid twice

1. **A `oneshot` service is killed as a process group when its main process
   exits.** The first version of the boot script started qrtr-ns, pd-mapper
   and the modem holder in the background and returned; init killed all of
   them ("Killed 3 additional processes from a oneshot process group"), and
   the modem went back to OFFLINE one second after reaching ONLINE.
2. **A service without `seclabel` is refused before it runs**, even in
   permissive mode: `File /system/bin/sh ... has incorrect label or no domain
   transition`. The domains this policy knows are `init`, `recovery`,
   `shell`; the recovery's own helpers use `u:r:recovery:s0`.
3. **`on early-init` cannot start a service.** That trigger runs in init's
   first stage, before services exist; the start is dropped silently and the
   second stage will not replay it. Use `on init`.
4. **Do not kill `pd-mapper` while the modem is up.** The kernel's locator
   client loses its server, the modem declares `Fatal error on the modem`
   two seconds later, and with `restart_level = SYSTEM` the whole phone
   restarts into the installed system — which is how several attempts ended
   with no log at all. The boot script now sets the modem's restart level to
   `RELATED` first, so a fault costs a log line instead.
5. **`adb reboot bootloader` does nothing on this phone** (Xiaomi ABL). To
   get to fastboot you power off and hold Volume-Down + Power. `fastboot
   boot` does not work either; only flashing the partition does.
6. **Do not flash the recovery partition while the phone is unstable.** One
   `dd` was interrupted by a modem-triggered reboot and left the partition
   half written: the recovery kernel could not mount its root
   (`kernel_panic, vfs: unable to mount root fs`), while the installed system
   still booted. Recovery: fastboot, then
   `fastboot flash recovery wlan-k*.img`.

## Artifacts

| File | What it is |
| --- | --- |
| `wlan-k12.img` | current image: bring-up at boot, modem restart level lowered, tools in `/skyward` |
| `wlan-k11.img` | same, plus automatic `wlfwd` (which died at boot; kept for reference) |
| `wlan-k10.img` | first image where the modem stayed up for the whole boot |
| `wlan-k8.img` / `wlan-k9.img` | the mount fix, then the ordered bring-up |
| `modem-up.sh` | the boot script, in `skyward/modem-up.sh` inside the ramdisk |
| `tools-src/` | sources for `modemhold`, `pd-mapper`, `qrtr-ns`, `qrtr-lookup`, `wlfwd`, `pdr-restart`, and the aarch64 build command |
| `tools-bin7/` | the older static binaries from CI |

`pd-mapper` here is patched twice beyond upstream: it reads the domain files
out of the firmware directory when `/sys/class/remoteproc` is empty (this
kernel has no remoteproc entries for the phone's processors), and it prints
`[PD-MAPPER] <name> -> N domain(s)` for every request so the modem's side of
the conversation is visible in `dmesg`.
