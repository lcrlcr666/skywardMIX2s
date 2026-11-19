# Skyward Recovery · 小米 MIX 2S（polaris）

把 [kirklin/skyward](https://github.com/kirklin/skyward) 移植到小米 MIX 2S：
A-only 分区适配、boot image v0–v2 与 gzip ramdisk、用这台手机上确定能启动的
recovery 做底，并由 GitHub Actions 直接构建出可刷镜像。

**已在真机上点亮**（见下「状态」）。

## 状态

| 项目 | 结果 |
| --- | --- |
| 刷入 recovery 分区后启动 | ✅ 界面出来、能操作（`polaris-v9` 起） |
| 显示（DRM） | ✅ legacy `set_crtc` + page flip，接管 bootloader 的 splash |
| 触摸 / 输入 | ✅ `/dev/input` 已打开 |
| 背光 | ✅ 面板 DT 节点名字对不上时回退到 `max_brightness` |
| 构建 | ✅ GitHub Actions |
| 底子 | OrangeFox R11.1 for polaris 的 `recovery.img` |
| 测试机 | Mi MIX 2S（polaris），InfinityX（Android 16），内核 4.19.325 |

还没适配：

| 项目 | 现在还缺什么 |
| --- | --- |
| 更新状态 / 系统信息 | 要把已装的 `system`/`vendor` 挂到**不遮住 ramdisk** 的位置（`/mnt/system`、`/vendor`），才能读 `build.prop` |
| `/data` 解密 | 这台机器是 `keymaster@4.0` + `gatekeeper@1.0`（`/vendor/lib64/hw` 里只有 `android.hardware.gatekeeper@1.0-impl-qti.so`），Skyward 的解密路径照的是新机的 `keymint`/`keystore2` |
| Wi-Fi | 要拉起 `wpa_supplicant`、加载 vendor 的 ko、对齐 ueventd 规则 |
| MTP / 双系统 / fastbootd / payload OTA | A-only + 无 super，本来就不适用或要另写 |

## 为什么用 OrangeFox 做底，而不是原厂 MIUI 的 recovery

Skyward 的做法是：**保留底子的 kernel 和 ramdisk，只把 `system/bin/recovery` 换成
它自己**。所以底子必须是这台机器上"确定能启动"的那一对 kernel + ramdisk。

- MIUI 12.5（Android 10）的原厂 recovery：4.9 内核 + 一个很小的 AOSP ramdisk。
  在现在跑 Android 16 / 4.19 的机器上试过两版，**屏幕始终黑**——Skyward 起来了、
  日志也写了，就是没画出东西。
- OrangeFox R11.1（`ro.twrp.version=R11.1_4`）：22.5 MB 内核 + 30 MB ramdisk，带一套
  Android 11 的完整 recovery userspace（`/system/lib64`、linker、toybox…）。这台机器
  上它本来就能启动，Skyward 换进去也起得来。

从正在运行的 OrangeFox 里读到的显示事实，也解释了为什么这条路对：

```
/dev/dri/card0  /dev/dri/controlD64  /dev/dri/renderD128     ← 没有 /dev/graphics
[ 0.97] [drm] found continuous splash base address:9d400000 size:2400000
msm_drm ae00000.qcom,mdss_mdp: bound ... dsi-display@18
```

这台机器的 recovery 就是走 DRM/KMS 的，Skyward 用 DRM 画屏正好对得上。

## 踩过的坑（都已在代码里修掉）

1. **ramdisk 就是 `/system`**。设备配置原来写 `mounted = ["system"]`，启动时把
   *已安装系统* 的 `/system` 挂到 recovery 自己的 `/system` 上 —— 于是 `/system/bin/sh`、
   `libc.so`、`adb shell` 全部失效（`Too many symbolic links`），该版本就是黑屏的元凶。
   现在只挂 `vendor`。
2. **底子不是"原厂"就拒绝**。打包器原本看到 `twres/`、`FFiles/`（第三方 recovery 自带页面）
   就直接 bail；现在改成**丢弃**这些目录继续：它们的空间正好给 Skyward 的界面用
   （`twres` 占 9.8 MB）。
3. **早退让界面永远出不来**。`misc` 读不到、USB 状态机没就绪都会让进程直接退出，
   init 立刻重启 → 黑屏死循环。现在这些失败只记录、不退出。
4. **日志活不过重启**。原来日志在 ramdisk（tmpfs）。现在优先写
   `/cache/skyward-recovery.log`；底子自带 fstab 读不出来时按分区名直接挂 `/cache`，
   所以黑屏也能事后取证。

## 从源码构建

```sh
cargo ndk -t arm64-v8a --platform 28 build --release -p skyward
RUSTFLAGS="-C target-feature=+crt-static" cargo ndk -t arm64-v8a --platform 28 build --release -p skyward-system-init --target-dir target/system-init
cargo build --release -p skyward-pack
STOCK=stock/recovery.img OUT=out/skyward-polaris.img ./scripts/build.sh
```

`stock/recovery.img` 就是底子（OrangeFox 的整分区镜像）。

### CI

`.github/workflows/build.yml`：Ubuntu 24.04 + Rust（`rust-toolchain.toml`）+ NDK r29 +
cargo-ndk，然后

1. 取底子镜像（`polaris-base` release 里的 `orange-fox-polaris.img`，按 SHA-256 校验并缓存）；
2. 编三个产物并打包：丢弃 `twres/FFiles/res`，换掉 `system/bin/recovery`，加字体与配置，
   按 64 MiB 分区补齐 AVB 尾；
3. `scripts/verify-image.py` 检查镜像结构（header、ramdisk、被替换的 recovery 程序、
   `ro.secure=0`、AVB 尾、整分区大小）；
4. `scripts/check-symbols.py` 拿 Skyward 的导入符号和底子 ramdisk 里的 `libc.so`/`liblog.so`
   对账——缺符号等于手机上加不起来。

全过才上传产物。

## 刷入

```sh
# 手机进 fastboot（关机后 音量- + 电源）
fastboot flash recovery skyward-polaris-V12.5.1.0.QDGCNXM.img
fastboot reboot        # 这台机器的 ABL 不认 "reboot recovery"，进系统后：
adb reboot recovery
```

> `fastboot boot` 在小米 ABL 上不生效（会直接回正常启动），只能刷进分区。

## 回滚

```sh
fastboot flash recovery offox-polaris.img     # polaris-base release 里那份
fastboot reboot
```

## 为什么还不做这些

- **`/data` 解密**：这台机器跑 Android 16，密钥服务是 `keymaster@4.0` / `gatekeeper@1.0`
  （`/vendor/lib64/hw` 里只有 `android.hardware.gatekeeper@1.0-impl-qti.so`），而 Skyward
  的解密路径是照新机的 `keymint` / `keystore2` 写的。
- **Wi-Fi**：要拉起 `wpa_supplicant` 与 vendor 的 `libwifi-hal`，还要让 `/vendor` 挂起来之后
  的 `ueventd` 规则对上，这是下一步。
- **MTP / 双系统 / fastbootd / payload OTA**：A-only、无 super，本来就不适用或要另写。

## 许可

GPL-3.0-or-later，见 `LICENSE`。上游：[kirklin/skyward](https://github.com/kirklin/skyward)。

## WLAN in recovery: what was tried, and where it stops (2026-11)

The kernel path was walked to the end on this device, and the results are
worth keeping:

- The recovery runs the phone's own kernel from its own partition, so any ROM
  boots it (v27). Wi-Fi needs the qcacld driver, which OrangeFox's kernel does
  not carry.
- A kernel was built from \ilcb/android_kernel_xiaomi_polaris\ (4.9, the
  polaris-specific tree) with \polaris_user_defconfig\, \CONFIG_QCA_CLD_WLAN=m\
  and \CONFIG_MODVERSIONS=n\. It boots, drives the panel, the data partition
  and adb, and the WLAN module loads (\wlan_hdd_state wlan major(215)
  initialized\).
- It is not enough: \icnss\ never boots the WLAN firmware, no \wlan\ platform
  driver appears under \/sys/bus/platform/drivers\, and this kernel's device
  tree registers no \wlan\/\wcnss\ entry under \/sys/bus/msm_subsys\. In an
  installed system the bring-up is done by the vendor's QMI/HAL userspace,
  which a recovery does not run.
- What a next attempt needs is not another compiler setting but that bring-up:
  either the vendor's cnss handshake in the recovery, or a device tree that
  declares the WLAN subsystem so the PIL can load \image/wlanmdsp.mbn\.

The build that got this far is kept as the \xperimental-kernel-wlan\
release; the image is built with \.github/workflows/kernel.yml\ and
\scripts/fix-kernel-tree.py\ in this repository.

### The vendor handshake was tried too

The modem's userspace daemon is on the vendor partition (\/vendor/bin/cnss-daemon\,
with \libqmi*\ beside it), and it is the piece that asks \icnss\ to boot the
WLAN firmware. It cannot run here: it is an Android 16 binary, and this
recovery's userspace is Android 11 — the system linker refuses it for
\memset_explicit\ (an Android 14 and later libc symbol), and the runtime
\/apex/com.android.runtime\ it needs is not on the system partition to mount
by hand (apexd builds it at boot).

So the last gap is not the kernel and not the configuration: it is that this
platform's WLAN bring-up lives in Android 16's userspace, and this recovery is
not Android 16. A recovery built from an Android 16 tree for this phone would
run the daemon as it is, and the kernel built here already supports it.

### The Android 16 runtime can be mounted inside the recovery

The vendor's daemon was taken further than expected:

\\\
mkdir -p /tmp/rt /tmp/rtm
cd /tmp/rt && unzip /system/apex/com.android.runtime.apex apex_payload.img
mount -t ext4 -o loop,ro /tmp/rt/apex_payload.img /tmp/rtm
mount -t ext4 -o ro /dev/block/by-name/vendor /vendor
mount -t vfat -o ro /dev/block/by-name/modem /vendor/firmware_mnt
LD_LIBRARY_PATH=/tmp/rtm/lib64/bionic:/system/lib64:/vendor/lib64:/vendor/lib64/hw \\
  /system/bin/linker64 /vendor/bin/cnss-daemon
\\\

That runs: the A16 runtime from the apex, the A16 linker and libraries from the
installed system, the daemon and its QMI libraries from the vendor partition,
and \image/wlanmdsp.mbn\ where the PIL looks for it. It exits at once, all the
same — it expects the environment its own init gives it (QMI service sockets and
properties), which a recovery does not provide.

So the chain is now: kernel boots with the WLAN module loaded, the firmware is
in place, and the vendor daemon can be started against the phone's own Android
16 runtime. What is missing is that daemon's environment, which is the piece to
work on next.

### The modem announces no services at all in the recovery

Three open tools were built for this and run here: wlfwd (the WLFW sequence
over QRTR), pd-mapper (which tells the modem where its protection domains
are) and pdr-restart. With the phone's own kernel, which has QRTR and the
WLAN driver built in, none of them can start anything:

\\\
qrtr-lookup 42   → no services        (the service registry)
qrtr-lookup 45   → no services        (the WLAN firmware service)
pd-mapper        → "failed to open remoteproc class", "no pd maps available"
\\\

So the modem's protection domains are not announced in this environment at all,
which is what Android's own init and its vendor services arrange at boot. The
tools are in \.github/workflows/tools.yml\ and ready; what is missing is the
boot-time integration that makes the modem enumerate its services.

### Why the open path cannot be finished on this phone

The open tools need kernel interfaces this phone's kernels do not have. From
the phone's own kernel configuration:

    # CONFIG_REMOTEPROC is not set
    # CONFIG_QCOM_RMTFS_MEM is not set
    CONFIG_QRTR=y

so the open bring-up (rmtfs -> pd-mapper -> wlfwd -> /dev/wlan) has nothing to
talk to, and pd-mapper says as much ("failed to open remoteproc class", "no pd
maps available"). The other kernel available for this phone, the polaris 4.9
tree, has neither 
et/qrtr, nor drivers/remoteproc, nor mtfs_mem, so it
cannot carry that path either.

What remains is the closed daemon, which is an Android 16 program, and this
recovery is Android 11: it loads and prints its own netlink handshake, then
dies before it reaches the firmware. A recovery built from an Android 16 tree
would run it as it is.

### The 4.19 tree is a mixture of kernel versions, not a buildable tree

halcyonlv/kernel_xiaomi_sdm845@16.2 is the only source for this phone with
QRTR *and* a path to remoteproc, so it was taken next. It does not compile, and
what it fails on says why: it carries the interfaces of one kernel generation
over the sources of another.

    include/linux/huge_mm.h        mmap_sem, renamed to mmap_lock everywhere else
    include/linux/mmu_notifier.h   a range type and event enum that nothing declares
    kernel/rcu/tasks.h             writes a task field this struct does not have
    mm/migrate.c                   calls the three-argument notifier the header no
                                   longer declares

The first three were patched here (\scripts/fix-kernel-tree.py\ and the build
step that follows it); the fourth is a call-site mismatch that only a
compatibility shim across many files would settle. Building it is a project of
its own, and whether the result boots is a further unknown.

### The last attempt: the 4.19 tree needs source surgery, not a setting

That tree carries two generations of the memory-notifier interface at once:

    mm/migrate.c, mm/memory.c    call mmu_notifier_invalidate_range_start with a
                                 range, and with a range's three parts
    include/linux/mmu_notifier.h declares only the one that takes a range

A plain macro for the three-part callers then breaks the one-part callers, so
what is left is renaming the real function and dispatching on the argument
count across the tree — source surgery with an unknown result afterwards, since
nothing says the kernel it produces will boot.
### The modem now comes up in the recovery (2026-11-19)

The blocker recorded above — "the modem announces no services at all" — is
gone. Three things were wrong, none of them the kernel configuration:

1. nothing mounted the `modem` partition, so the kernel asked ueventd for
   `modem.mdt` and ueventd looked only in `/etc/firmware`, `/odm/firmware`,
   `/vendor/firmware` and `/firmware/image`. Mounting the partition at
   `/firmware` is the whole fix for the modem; the `OFFLINING` state that was
   blamed earlier is what a failed get leaves behind, not its cause.
2. the bring-up has an order — `qrtr-ns`, then `pd-mapper`, then the open
   that starts the processor — and the locator has to be up *before* the
   modem, or the modem boots into a locator that is not there;
3. a `oneshot` init service is killed as a process group when its main
   process exits, which takes the name service, the locator and the holder
   down with it.

With those fixed, one boot gives:

    4.83 modem-up: qrtr-ns started
    4.84 servloc: service_locator_new_server: Connection established
    4.84 [PD-MAPPER] wlan/fw -> 1 domain(s)
    7.44 modemhold: modem opened, holding
    8.09 modem-up: modem state ONLINE

and the name service lists the modem's services, WCNSS's DIAG channels
included. The WLAN driver loads (`wlan_hdd_state wlan major(488)`), `/dev/wlan`
appears — and `echo ON > /dev/wlan` stops at `icnss: FW is in bad state,
state: 0x4180`, because the firmware has not published the WLFW service
(`qrtr-lookup 69` is empty). That is where the work now stops, and it is a
userspace problem: on this phone the domain is turned on by the vendor's
`cnss-daemon`, as the sections above describe.

`docs/wlan-bring-up.md` has the logs, the order that works, and the six
mistakes that cost the most time (including "do not kill the locator while
the modem is up": the modem faults and, at its default restart level, the
whole phone restarts).
### The last step: the modem does not announce its WLAN domain (2026-11-19)

With the modem up and the locator answering, one step is still missing, and it
is now measured rather than guessed.  In the installed system the modem
announces its WLAN protection domain 0.7 s after it comes out of reset:

    service-notifier: Indication received from msm/modem/wlan_pd, state: 0x1fffffff
    icnss_qmi: QMI Server Connected: state: 0x980
    icnss: WLAN FW is ready: 0xd87

In the recovery the same modem, the same firmware and the same maps give the
notifier connection and then nothing, and the modem faults on its own about
43 s later.  In the installed system the QRTR name service carries the modem's
whole QMI stack (WDS, DMS, NAS, IPA control, ten TFTP endpoints, the remote file
system service); in the recovery it carries only SSCTL, servreg and the DIAG
channels.  That difference is the remaining work — see
`docs/wlan-bring-up.md`, section "Second session".

### File transfer (MTP) in the recovery

Two things kept MTP from working, both in the base ramdisk rather than in
Skyward.  `scripts/patch-mtp.py` fixes them for a packed image, and the
effects are visible in one boot's log:

    [3.9] shared-storage: /data mounted by this script
    [4.3] skyward: mtp: the computer configured the function
    [4.4] skyward: mtp: the computer opened a session
    [5.1] shared-storage: /sdcard now shows /data/media/0
    [5.3] shared-storage: shared storage: 24 entries, writable=yes

1. The base's `init.recovery.usb.rc` binds the *kernel's* MTP function
   (`mtp.gs0`) for `mtp,adb`; Skyward serves MTP over FunctionFS (`ffs.mtp`).
   Both write the same symlink `configs/b.1/f1`, the base rule runs first and
   its `symlink` succeeds, so Skyward's fails with the link in place and the
   computer is left with a function nobody serves: the phone enumerates and
   no storage ever appears.  The base rule is removed; `skyward-mtp.rc` binds
   `ffs.mtp` once adbd and the MTP port are both ready.
2. Nothing mounts `/data` at boot in this base (only `/cache` comes up) and
   nothing binds `/data/media/0` onto `/sdcard`, which is what File transfer
   offers.  `shared-storage.sh` mounts the partition (f2fs, writable) and does
   the binding.  The files come out in the clear on this phone, so a computer
   can read them without the credential.

### The modem needed its file system: RMTFS and the EFS partitions

The modem faulted about forty seconds after coming up, every time, and the
kernel log said nothing except `Fatal error on the modem`.  It was the modem's
own fault, and the line that explains it is one from **rmtfs**:

    [storage] failed to open '/boot/modem_fs1': No such file or directory
    Fatal error on the modem.

The modem asks RMTFS for its file system as it boots (`modem_fs1`, `modem_fs2`,
`modem_fsc`, `modem_fsg`).  rmtfs maps those onto the phone's EFS partitions
(`modemst1`, `modemst2`, `fsc`, `fsg`) by **partition label**, under
`/dev/disk/by-partlabel`, which this recovery's ueventd does not create - and
without `-P` it looks for the images as files in `/boot` instead.  With both
fixed (the links made by the boot script, `rmtfs -P`), the modem boots and
stays up:

    modem-up: wlan module loaded, rc=0
    modem-up: rmtfs started with the EFS partitions
    modem-up: modem state ONLINE
    modem-up: settled at ONLINE          <- and no "Fatal error" after it

The QRTR name service went from 28 services to 69 with it, and now carries
this recovery's own `Remote file system service` and `TFTP` endpoints.

What is still missing is the firmware's WLFW service (`qrtr-lookup 69`): the
modem never announces its `wlan_pd` protection domain here, though it does in
the installed system 0.7 s after coming out of reset.  The next thing to look
at is the IPA firmware (`ipa_fws`), which the installed system brings up at
boot (`ipa3_handle_indication_req` sits right beside the domain's indication
there) and which is never started here; its image is on the vendor partition,
so `/vendor` has to be mounted where the firmware loader looks.

### After the modem's file system: everything but WLFW

With RMTFS serving the EFS partitions the modem comes up and stays up, and its
whole QMI stack is published — the name service now carries the same shape as
the installed system's: WDS, DMS, NAS, QoS, WMS, UIM, IMS, PDS, thermal, the
subsystem control service, IPA control, and this recovery's own remote file
system and TFTP endpoints (67 services).

The host side of the WLAN bring-up is then complete and can be read off one
boot:

    3.99  wlan: Loading driver v5.2.022.12B
    4.39  wlan_hdd_state wlan major(488) initialized
    5.44  [PD-MAPPER] wlan/fw -> 1 domain(s)          <- icnss's locator query
    10.46 service-notifier: new_server ... 180 service <- listener registered
    ...   (nothing)                                    <- no announcement

The installed system gets one line here that this recovery never does:

    service-notifier: Indication received from msm/modem/wlan_pd, state: 0x1fffffff

and everything after it (`icnss_qmi: QMI Server Connected`, `WLAN FW is
ready`) follows.  So the modem simply never starts its `wlan_pd` protection
domain here, and that is the whole of what is left.

Tried on this round, without success:

* the installed system's `cnss-daemon`, run under the Android 16 runtime
  (extracted from `com.android.runtime.apex`, mounted, A16 linker and
  libraries).  It runs — it stays up for as long as it is attached to a
  terminal — but the modem still publishes no WLFW;
* starting the IPA firmware, which the installed system brings up at boot and
  this recovery never does.  With `/vendor` mounted so the loader can see
  `/vendor/firmware/ipa_fws.mdt`, opening `/dev/subsys_ipa_fws` loads the image
  from `0x8c400000` and then the phone hangs and the watchdog restarts it.

### What "automatic decryption" means for this phone, and for Android 8–17

Measured on the phone: **its data partition is not encrypted**.  A read of
`/data/system/packages.xml` from the recovery returns Android's plain binary
XML (`ABX\0` …), `/data/misc/vold` does not exist, and
`/data/media/0` holds the owner's files in the clear.  So there is nothing to
decrypt here, and what "automatic" needs is only what is already in the boot
script: mount the partition and bind `media/0` onto `/sdcard` — which is what
makes File transfer show the phone's folders.

For Skyward in general the picture is wider, and this phone is the easy case:

| Android | Storage encryption | What a recovery needs |
| --- | --- | --- |
| 8, 9 | full-disk (FDE): one dm-crypt mapping for all of `/data` | the key from `vold`/`cryptfs`, unwrapped through keymaster 1.0/3.0, then a plain dm-crypt mount |
| 10, 11 | file-based (FBE) with keymaster 3.0/4.0, gatekeeper 1.0, keystore 1.0 | a keymaster client over binder for the per-user and per-file keys, then fscrypt |
| 12–17 | FBE with keymint and keystore2, plus metadata encryption | what `skyward-crypto` implements today (`keymint.rs`, `keystore2.rs`, `fscrypt.rs`, `gatekeeper.rs`, `locksettings.rs`, `user.rs`) |

So 12–17 is the modelled case, 10–11 needs a keymaster-3/4 client beside the
keymint one, and 8–9 needs an FDE path that does not exist in the tree at all.
That is a feature of the crypto crate, not of this port.

### The one kernel-side difference left: IPA firmware never loads here

The installed system loads the IPA firmware during boot and says so:

    IPA FW loaded successfully

This recovery never does.  Its IPA driver does bind (`/sys/bus/platform/drivers/ipa`
holds `1e00000.qcom,ipa`), but the firmware behind it is never started:

    # CONFIG-free: ipa_fws subsystem state stays OFFLINING
    ipa ipa3_uc_state_check:488 uC interface not initialized

Loading it by hand (`open("/dev/subsys_ipa_fws")` with `/vendor` mounted so the
loader can see `ipa_fws.mdt`) does start it — `ipa_fws: loading from
0x8c400000` — and then hangs the phone in the middke of the segment requests,
which the watchdog turns into a restart.  Twice.

That is where the WLAN bring-up now stands: every piece on the host side is in
place (driver, its configuration from `/vendor/firmware/wlan/qca_cld`, the
locator's answer, the listener registered with the modem's servreg), and the
modem is healthy — but the firmware never starts its `wlan_pd` domain, and the
IPA firmware, which the installed system brings up and this kernel cannot, is
the last measurable difference.

### What was ruled out on the way (round 5)

* **Starting the domain from the host is refused.**  `pdr-restart 0 1
  msm/modem/wlan_pd` against the modem's own servreg notifier answers
  `result 1 error 9` (disabled / not supported) on a perfectly healthy modem,
  so the host cannot ask for the domain to be started or restarted.
* **The installed system's daemons do not run here.**  `cnss-daemon` and
  `ipacm`, run under the Android 16 runtime, only *look* alive: attached to a
  terminal they stay up, detached with `setsid` and a closed stdin they exit at
  once and write nothing.  A daemon that exits when it is not attached to a pty
  is a daemon failing its own start-up here, not one working.
* **The installed system's ordering** supports the IPA hypothesis:
  `ipa_fws: Brought out of reset` / `IPA FW loaded successfully` appear about
  four seconds into its boot, long before the modem start that makes it
  announce `wlan_pd` (which follows 0.7 s after the modem comes out of reset).

### A kernel that can be asked what it is doing (round 6)

`kernel.yml` now builds with `CONFIG_DEBUG_FS` and `CONFIG_DYNAMIC_DEBUG`, and
that changes the diagnosis from guessing to reading.  What icnss says about
itself, with its own debug prints turned on at runtime
(`echo "file icnss.c +p" > /sys/kernel/debug/dynamic_debug/control`):

    icnss: Registering driver, state: 0x180
    icnss: Processing event: REGISTER_DRIVER(3), state: 0x180
    icnss: FW is not ready yet, state: 0x180

and `/sys/kernel/debug/icnss/stats` gives the state plainly:

    SERVER_ARRIVE 0    FW_READY 0    REGISTER_DRIVER 0 (before) / processed (after)
    State: 0x180(SSR REGISTERED | PDR REGISTERED)

So the host's half is not merely "probably fine": icnss registers the driver,
is in PDR mode, and waits for the firmware's WLFW service — which never
appears.  On the IPA side there is no `/sys/kernel/debug/ipa` at all (only
`ipa_usb` and `rmnet_ipa`), which is the same conclusion from the other
direction: the IPA driver never finished its initialisation here.

### Building a kernel into this image

The recovery image's kernel section is **`Image.gz` followed by the phone's
device tree** (6,284,856 bytes, `rom.dtb`), not `Image.gz` alone; an image built
without the tail does not boot (the bootloader drops to fastboot).  With the
tail, the CI-built kernel composes straight onto this work's ramdisk:

    python mk-k28.py k419e/Image.gz     # k419e = the workflow's artifact

and the module that goes with it is that artifact's `qca_cld3_wlan.ko`.

### The IPA firmware loads now — and what that changed (round 7)

The IPA driver's own entry point for its firmware is a write to `/dev/ipa`
(`ipa3_write` → `ipa3_fw_loading_work`), not a hand-opened subsystem.  With
`echo 1 > /dev/ipa` the driver loads it exactly as the installed system does:

    ipa ipa3_uc_response_hdlr: IPA uC loaded
    QMI_IPA_INIT_MODEM_DRIVER_REQ_V01 response received
    ipa_fws ONLINE

and the boot script now does that **before the modem is started**, which is the
order the installed system runs in.  That brought one new piece of evidence: on
a modem restart with IPA up, icnss received a protection-domain notification for
the first time —

    icnss: PD service notification: 0x7fffffff state: 0x4180

— but with state `0x7fffffff`, which is *down* (`0x1fffffff` is what the
installed system sees when the domain comes up), so the domain is still not
started.  A full boot with IPA already up (k29) gives the same: IPA's handshake
with the modem completes (`IPA received MPSS AFTER_POWERUP`,
`QMI_IPA_INIT_MODEM_DRIVER_REQ_V01 response received`), the modem is ONLINE,
and `qrtr-lookup 69` is still empty.
