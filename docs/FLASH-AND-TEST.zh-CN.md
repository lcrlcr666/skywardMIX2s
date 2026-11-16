# 刷入与测试 · 小米 MIX 2S（polaris）

镜像是在 **OrangeFox R11.1 的 `recovery.img`** 上盖出来的：OF 的内核、init、adbd、
`/system/lib64` 全部保留，只把 `system/bin/recovery` 换成 Skyward。所以显示和触摸
用的是这台手机自己的驱动与 DRM。

> 为什么不用原厂 MIUI 的 recovery 做底：它在跑 Android 16 / 内核 4.19 的机器上点不亮
> （Skyward 跑起来了但屏幕黑）。OF 的 kernel + ramdisk 是这台机器上确定能启动的那一对。
> 详见仓库 README 的「为什么用 OrangeFox 做底」。

## 产物

| 文件 | 说明 |
| --- | --- |
| `skyward-polaris-V12.5.1.0.QDGCNXM.img` | 整分区镜像，正好 **67,108,864 字节（64 MiB）** |
| `skyward-polaris-V12.5.1.0.QDGCNXM.zip` | 上面那个 img 的 zip |
| `SHA256SUMS` | 校验和 |
| `offox-polaris.img`（`polaris-base` release） | 回滚用：OrangeFox 整分区镜像 |

## 刷入

```sh
# 手机进 fastboot（关机后按住 音量- + 电源）
fastboot devices
fastboot flash recovery skyward-polaris-V12.5.1.0.QDGCNXM.img
fastboot reboot          # 这台机器的 ABL 不认 "reboot recovery"
adb reboot recovery      # 进系统后再进 recovery
```

> **`fastboot boot` 在这台机器上不生效**：ABL 会忽略它，直接正常启动进系统。

## 回滚

```sh
fastboot flash recovery offox-polaris.img
fastboot reboot
```

## 开机后看什么

1. **屏幕**：Skyward 首页（"Skyward" 标题、搜索框、WLAN / 原生启动 / 安装 / 备份 /
   恢复 / 挂载 / 解密 / 高级）。
2. **触摸**：点「设置」能翻页。
3. **adb**：`adb devices` 看到 `recovery`；`adb shell id` 是 `uid=0`。

## 黑屏时怎么取证（这版已经有日志了）

镜像会把启动过程写进 **`/cache/skyward-recovery.log`**（`/cache` 是 ext4，重启后还在）：

```sh
adb pull /cache/skyward-recovery.log
```

里面依次会出现：

```
polaris 0.2.0 recovery up, misc command "" asking for Menu
clock set … / the CPUs run as the system runs them …
vendor is mounted on /vendor            ← 或 vendor is not mounted: …
the typefaces are loaded
the screen is up: 1080x2160, …          ← 到这一步说明 DRM 开了屏
kms: connector … / crtc … / plane …     ← 显示器的真实状态
the input devices are open
the backlight is open, drawing the first page
```

停在哪一行，问题就在那一步之后。要是连 `adb` 都没有，用 OrangeFox 打开 `/cache`
把文件拷出来（OF 的文件管理能看 `/cache`）。

## 已知未适配

- `/data` 解密（这台机器是 Android 16 + `keymaster@4.0`/`gatekeeper@1.0`，Skyward 的解密
  是照 `keymint`/`keystore2` 写的）
- Wi-Fi、MTP、双系统、fastbootd、payload OTA

## 这份镜像是怎么构建的

见仓库 README 的「CI」一节，或 `.github/workflows/build.yml`：取 OF 底子 → 编三个产物 →
丢弃 `twres/FFiles/res` 后打包 → 结构自检 + 符号自检 → 上传产物。
