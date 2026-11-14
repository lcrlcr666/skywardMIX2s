# 刷入与测试 · 小米 MIX 2S（polaris）

这份镜像是在**这台手机自己的原厂 recovery** 上盖出来的：原厂的 init、adbd、SELinux
策略、驱动库、触摸固件都保留，只把 `system/bin/recovery` 换成 Skyward，所以显示、
触摸走的是这台手机自己的驱动。原厂基线是 MIUI **V12.5.1.0.QDGCNXM**（Android 10）。

## 产物

| 文件 | 说明 |
| --- | --- |
| `skyward-polaris-V12.5.1.0.QDGCNXM.img` | 整分区镜像，正好 **67,108,864 字节（64 MiB）** |
| `skyward-polaris-V12.5.1.0.QDGCNXM.zip` | 上面那个 img 的 zip |
| `SHA256SUMS` | 校验和 |

`polaris-stock-recovery.img` 是这台手机的原厂 recovery 分区镜像（58,520,910 字节，
无 AVB 尾部填充），**刷机前请先留一份**，它是回滚用的。

## 刷之前

1. 确认 Bootloader 已解锁（`fastboot oem device-info` 里 `Device unlocked: true`）。
2. 确认底包是 V12.5.1.0.QDGCNXM。别的版本内核/驱动可能对不上，先刷回该版本更稳。
3. 备份原厂 recovery（两种办法，任选）：

   ```sh
   # 在系统里（有 root）
   adb shell su -c 'dd if=/dev/block/bootdevice/by-name/recovery of=/sdcard/stock-recovery.img'
   adb pull /sdcard/stock-recovery.img
   ```

   或者直接用本仓库 Release 里那份 `polaris-stock-recovery.img`（同一底包、同一分区）。

## 先试跑，再决定刷不刷

解锁后的 ABL 支持 `fastboot boot`：把镜像放进内存直接启动，**不写 recovery 分区**。
这是最省事的验证方式，坏了重启就回到原样：

```sh
# 手机进 fastboot（关机后按住 音量- + 电源）
fastboot devices
fastboot boot skyward-polaris-V12.5.1.0.QDGCNXM.img
```

镜像比 `boot` 多了 AVB 尾（它按 64 MiB 分区补齐），bootloader 按 header 里的
kernel/ramdisk 长度取，多出来的尾巴不理它。

想长期用时再刷进分区：

```sh
fastboot flash recovery skyward-polaris-V12.5.1.0.QDGCNXM.img
fastboot reboot recovery
```

> 刷进分区后，MIUI 系统更新可能把 recovery 换回原厂；Skyward 设置里有"再次刷入
> Skyward"，打开后系统更新也会保留它。

## 回滚

```sh
fastboot flash recovery polaris-stock-recovery.img
fastboot reboot
```

只是 `fastboot boot` 试过、没刷分区的话，不需要回滚，重启即可。

## 第一次启动要看什么

按这个顺序看，坏在哪一步就知道问题在哪：

1. **屏幕亮不亮**：Skyward 首页出现（左上 "Skyward"、搜索框、"WLAN / 原生启动 / 安装 /
   备份 / 恢复 / 挂载 / 解密 / 高级"）。黑屏但背光亮 → 显示通路（panel/DRM）没接上。
2. **触摸有没有反应**：点"设置"能翻页。没反应 → 触摸驱动没加载（`/vendor/lib/modules`
   里的 ko，或 `/dev/input` 没事件）。
3. **adb**：`adb devices` 应该直接看到设备且是 root，**不需要在手机上点授权**：

   ```sh
   adb devices
   adb shell id          # uid=0
   adb shell getprop ro.secure      # 0
   ```

4. **/data 解密**：首页"解密"里输入锁屏密码，能挂上 `/data` 就是通了（Android 10 +
   高通 keymaster，Skyward 上游是照新系统的 keymint/keystore2 写的，这一步在旧机型上
   最可能不通，不通也不影响其它功能）。
5. **WLAN**：设置里开 Wi-Fi，能看到热点列表。
6. **MTP**：插电脑能识别成存储设备。

## 卡住了怎么抓信息

- Skyward 自己的日志：`adb shell cat /skyward/run/recovery.log`
- 内核日志：`adb shell dmesg`（adb 能用就有）
- adb 也不通时：重启前内核最后的话在 `pstore` / `ramoops` 里，下次进系统后：

  ```sh
  adb shell su -c 'cat /sys/fs/pstore/console-ramoops*'
  ```

  或者用 Skyward 的"高级 → 日志"页（能进 UI 的话）。

## 已知限制

- 没有 fastbootd、没有 A/B 切槽、没有 payload OTA、没有双系统 —— MIX 2S 是 A-only +
  system-as-root，没有动态分区，这些对它本来也不适用。
- 字体是子集（ASCII + 拉丁补充 + 常用标点 + GB2312 6763 汉字），生僻字/繁体可能显示
  成方框：64 MiB 分区里 kernel 就占了 42 MiB，20 MiB 的完整 MiSans 放不下。
- 原厂 `res/images/`（8.3 MiB 界面图片）在打包时丢掉了，Skyward 自己画界面。
- 这台机器没有 `/metadata` 分区（Android 8 时代机型），Skyward 的设置项可能存不住，
  它会退回默认值并把原因写进内核日志。

## 这份镜像是怎么构建的

`.github/workflows/build.yml`：Ubuntu 24.04 + Rust（`rust-toolchain.toml`）+ NDK r29 +
cargo-ndk，然后

1. 取原厂 recovery 分区镜像（缓存 30 天，缓存命中就不重下）；
2. `scripts/build.sh` 编三个产物并打包：`skyward`（设备端，API 28）、
   `skyward-system-init`（静态）、`skyward-pack`（主机端）；
3. `scripts/verify-image.py` 检查镜像本身：header 版本、ramdisk 是否能解、
   `system/bin/recovery` 是否已被换成 Skyward、`ro.secure=0`/`ro.adb.secure=0`
   是否写进 `prop.default`、AVB 尾部是否正好落在 64 MiB 分区末尾；
4. `scripts/check-symbols.py` 拿 Skyward 的导入符号去原厂 ramdisk 里的
   `libc.so`/`liblog.so` 等对账 —— 缺一个符号，手机上是"程序还没跑就加载失败"，
   这一步就是为了在不出机器的情况下拦住它。

只有这四步全过，镜像才会上传。
