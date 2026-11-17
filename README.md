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