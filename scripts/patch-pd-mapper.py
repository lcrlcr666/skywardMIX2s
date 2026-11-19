#!/usr/bin/env python3
"""Patch pd-mapper for this phone, in a tree freshly cloned from upstream.

Three things are wrong with upstream here, and all three are about *where* the
domain files are and *what can be seen* of the conversation:

  * on this phone the modem and the WLAN processor are taken up by the older
    PIL drivers, so /sys/class/remoteproc exists and has no entries.  Upstream
    reads the firmware path out of a remote processor's `firmware` attribute
    and finds none, so it loads no maps at all ("no pd maps available").  The
    domain files are in the modem partition; they are read directly when the
    enumeration comes back empty;
  * the files are in the modem partition, not in /vendor/firmware, so the
    scan goes to the directory the kernel was told to load firmware from,
    with the vendor's own path as a fallback;
  * nothing on either side of the locator conversation is visible in a log.
    Every request is printed with the number of domains answered, and every
    map file is named, so a silent zero can be told from a parse failure.

Usage: patch-pd-mapper.py <path to the pd-mapper checkout>
"""

import pathlib
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "pd-mapper")
src = root / "pd-mapper.c"
text = src.read_text()
original = text

# 1. name the map file, and say why loading it failed
old = "\tret = pd_load_map(jsn);\n\t\tif (ret < 0)\n\t\t\tbreak;"
new = (
    "\tfprintf(stderr, \"loading map %s\\n\", jsn);\n"
    "\t\tret = pd_load_map(jsn);\n"
    "\t\tif (ret < 0) {\n"
    "\t\t\tfprintf(stderr, \"map %s failed: %d\\n\", jsn, ret);\n"
    "\t\t\tbreak;\n"
    "\t\t}"
)
if old in text:
    text = text.replace(old, new, 1)
    print("map loading is reported")
else:
    print("map report patch did not match")

# 2. read the domain files out of the firmware directory when the remote
#    processor class gives nothing to read a path from
fallback = '''/*
 * The phone announces no remote processors to this kernel: the modem and the
 * WLAN processor are taken up by the older PIL drivers, so /sys/class/
 * remoteproc exists and is empty, and the enumeration above finds nothing to
 * read a firmware path out of.  The domain files are in the modem partition
 * all the same, and their directory is the one the kernel was told to load
 * firmware from - so that directory is read directly when the enumeration
 * comes back with nothing.
 */
static int pd_enumerate_dir(struct assoc *json_set, const char *dir)
{
\tchar json_path[PATH_MAX];
\tstruct dirent *de;
\tsize_t len;
\tDIR *d;
\tint added = 0;

\td = opendir(dir);
\tif (!d)
\t\treturn 0;

\twhile ((de = readdir(d)) != NULL) {
\t\tlen = strlen(de->d_name);
\t\tif (len < 5 || strcmp(de->d_name + len - 4, ".jsn"))
\t\t\tcontinue;
\t\tif (strlen(dir) + 1 + len + 1 > sizeof(json_path))
\t\t\tcontinue;

\t\tsnprintf(json_path, sizeof(json_path), "%s/%s", dir, de->d_name);
\t\tassoc_set(json_set, json_path, NULL);
\t\tadded++;
\t}

\tclosedir(d);
\treturn added;
}

static void pd_enumerate_firmware_dir(struct assoc *json_set)
{
\tstatic const char *fallbacks[] = {
\t\t"/vendor/firmware_mnt/image",
\t\t"/firmware/image",
\t\t"/lib/firmware",
\t\tNULL,
\t};
\tchar fw_path[PATH_MAX];
\tssize_t n;
\tsize_t i;
\tint fd;

\tfd = open("/sys/module/firmware_class/parameters/path", O_RDONLY);
\tif (fd >= 0) {
\t\tn = read(fd, fw_path, sizeof(fw_path) - 1);
\t\tclose(fd);
\t\tif (n > 1) {
\t\t\tfw_path[n - 1] = '\\0';
\t\t\tif (pd_enumerate_dir(json_set, fw_path))
\t\t\t\treturn;
\t\t}
\t}

\tfor (i = 0; fallbacks[i]; i++)
\t\tif (pd_enumerate_dir(json_set, fallbacks[i]))
\t\t\treturn;
}

static int pd_load_maps(void)
'''
anchor = "static int pd_load_maps(void)\n"
if "pd_enumerate_dir(" not in text and anchor in text:
    text = text.replace(anchor, fallback, 1)
    text = text.replace(
        "\tpd_enumerate_jsons(&json_set);\n",
        "\tpd_enumerate_jsons(&json_set);\n"
        "\tif (!json_set.fill)\n"
        "\t\tpd_enumerate_firmware_dir(&json_set);\n",
        1,
    )
    print("the firmware directory is read when no remote processor is named")
else:
    print("firmware directory patch did not match")

# 3. say what the modem asked for and what it was answered
old = (
    "\tresp.total_domains_valid = 1;\n"
    "\tresp.total_domains = resp.domain_list_len;\n"
    "\nrespond:\n"
)
new = (
    "\tresp.total_domains_valid = 1;\n"
    "\tresp.total_domains = resp.domain_list_len;\n"
    "\n"
    "\t/* The phone's services ask by name and there is nothing else to watch\n"
    "\t   on the other side of this: say what was asked for and what was\n"
    "\t   answered. */\n"
    "\tfprintf(stderr, \"[PD-MAPPER] %s -> %d domain(s)\\n\",\n"
    "\t\treq.name, resp.domain_list_len);\n"
    "\nrespond:\n"
)
if old in text:
    text = text.replace(old, new, 1)
    print("requests are reported")
else:
    print("request report patch did not match")

if text != original:
    src.write_text(text)
    print("patched:", src)
else:
    print("nothing changed")
