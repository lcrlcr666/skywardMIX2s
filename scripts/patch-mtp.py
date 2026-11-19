#!/usr/bin/env python3
"""Patch a base ramdisk so file transfer works in the recovery.

Three things in the base are wrong for Skyward on this phone, and they are
all in the base's own files rather than in Skyward:

1. `init.recovery.usb.rc` binds the *kernel's* MTP function (`mtp.gs0`) when
   `sys.usb.ffs.ready` is set and `sys.usb.config` is `mtp,adb`.  Skyward
   serves MTP over FunctionFS (`ffs.mtp`), and its own rule binds that.  Both
   act on the same symlink, `configs/b.1/f1`; the base rule runs first, its
   symlink succeeds, and the Skyward one then fails because the link exists.
   The computer is left looking at a function nobody serves: the phone
   enumerates and no storage ever appears.  The base rule is removed here.

2. Nothing mounts the data partition at boot on this base (only /cache comes
   up), so `/data/media/0` is not there to show.

3. Nothing binds `/data/media/0` onto `/sdcard`, which is what File transfer
   offers to the computer.  Android's vold does that when a user is unlocked
   and Skyward does it in its own data-partition flow; a recovery does
   neither, so `/sdcard` stays an empty directory in the ramdisk.

(2) and (3) are handled by a small service, `skyward/shared-storage.sh`,
added to the ramdisk and started from `on init`.

Usage: patch-mtp.py <ramdisk tree>
"""

import pathlib
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
changed = []

BASE_RULE = """on property:sys.usb.ffs.ready=1 && property:sys.usb.config=mtp,adb && property:sys.usb.configfs=1
    write /config/usb_gadget/g1/configs/b.1/strings/0x409/configuration "mtp_adb"
    rm /config/usb_gadget/g1/configs/b.1/f1
    rm /config/usb_gadget/g1/configs/b.1/f2
    rm /config/usb_gadget/g1/configs/b.1/f3
    rm /config/usb_gadget/g1/configs/b.1/f4
    rm /config/usb_gadget/g1/configs/b.1/f5
    write /config/usb_gadget/g1/idVendor 0x2717
    write /config/usb_gadget/g1/idProduct 0xff68
    symlink /config/usb_gadget/g1/functions/mtp.gs0 /config/usb_gadget/g1/configs/b.1/f1
    symlink /config/usb_gadget/g1/functions/ffs.adb /config/usb_gadget/g1/configs/b.1/f2
    write /config/usb_gadget/g1/UDC ${sys.usb.controller}
    setprop sys.usb.state ${sys.usb.config}
"""

REPLACEMENT = """# The MTP function is bound by skyward-mtp.rc, which waits for both adbd and
# the MTP port: the rule that used to be here bound the kernel's own mtp.gs0
# function, and Skyward's MTP runs over FunctionFS.  Both act on the same
# symlink, so the one that ran first won and the computer was left with a
# function nobody served.
on property:sys.usb.ffs.ready=1 && property:sys.usb.config=mtp,adb && property:sys.usb.configfs=1
    setprop sys.usb.state ${sys.usb.config}
"""

SERVICE = """on init
    start shared-storage

# The data partition is not mounted by this base at boot, and the owner's
# media folder is not bound onto /sdcard, which is what File transfer offers.
service shared-storage /system/bin/sh /skyward/shared-storage.sh
    class core
    user root
    group root
    oneshot
    seclabel u:r:recovery:s0
"""


def patch(path, edit):
    p = root / path
    if not p.exists():
        print(f"missing: {path}")
        return
    text = p.read_text(errors="replace")
    new = edit(text)
    if new != text:
        p.write_text(new)
        changed.append(str(path))
        print(f"patched: {path}")
    else:
        print(f"unchanged: {path}")


def usb_rc(text):
    if BASE_RULE in text:
        return text.replace(BASE_RULE, REPLACEMENT, 1)
    return text


patch("init.recovery.usb.rc", usb_rc)


def init_rc(text):
    if "shared-storage" in text:
        return text
    return text.rstrip("\n") + "\n\n" + SERVICE


patch("system/etc/init/hw/init.rc", init_rc)

print("changed:", ", ".join(changed) if changed else "nothing")
