"""Build the firmware with the project's effects in it, and send it to the device.

The export already makes a usermod folder. This stages it into the WLED
tree's `usermods/`, writes an environment into `platformio_override.ini`
that extends the one chosen - its usermods plus ours - runs PlatformIO on
it, and posts the binary to the device's `/update`, as the web UI's update
page does. Everything runs on a worker; the lines it prints go to a queue
the dialog drains.

    job = Job(project, base_env="esp32dev_customfx", host="192.168.1.50", build=True, upload=True)
    job.start()
    while not job.done: line = job.q.get_nowait() ...
"""
import configparser
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from native.project import ROOT

USERMOD = "usermod_studio"
MARK_BEGIN = ";; --- WLED Effect Studio: generated environment (rewritten on every flash) ---"
MARK_END = ";; --- end WLED Effect Studio ---"


def pio_exe():
    """PlatformIO's command line, on the path or in its own virtualenv."""
    p = shutil.which("pio") or shutil.which("platformio")
    if p:
        return p
    home = os.path.expanduser("~/.platformio/penv")
    for c in (os.path.join(home, "Scripts", "pio.exe"), os.path.join(home, "bin", "pio")):
        if os.path.exists(c):
            return c
    return None


def _ini(path):
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    if os.path.exists(path):
        cp.read(path, encoding="utf-8")
    return cp


def read_envs():
    """([env names], default) from platformio.ini and the override; the
    studio's own generated envs are left out of the list."""
    base = _ini(os.path.join(ROOT, "platformio.ini"))
    over = _ini(os.path.join(ROOT, "platformio_override.ini"))
    names = []
    for cp in (over, base):                       # the user's own first
        for sec in cp.sections():
            if sec.startswith("env:") and not sec.startswith("env:studio_") and sec[4:] not in names:
                names.append(sec[4:])
    default = None
    for cp in (over, base):
        if cp.has_option("platformio", "default_envs"):
            default = cp.get("platformio", "default_envs").split(",")[0].strip().split("\n")[0]
            break
    if default and default.startswith("studio_"):
        default = default[7:]
    return names, default if default in names else (names[0] if names else None)


def usermods_of(env):
    """The custom_usermods an env ends up with, following `extends`."""
    base = _ini(os.path.join(ROOT, "platformio.ini"))
    over = _ini(os.path.join(ROOT, "platformio_override.ini"))
    seen = set()
    while env and env not in seen:
        seen.add(env)
        sec = "env:" + env
        for cp in (over, base):
            if cp.has_section(sec):
                if cp.has_option(sec, "custom_usermods"):
                    return [u.strip() for u in cp.get(sec, "custom_usermods").replace(",", "\n").split("\n") if u.strip()]
                nxt = cp.get(sec, "extends", fallback=None)
                env = nxt.strip()[4:] if nxt and nxt.strip().startswith("env:") else None
                break
        else:
            env = None
    return []


def stage(project, base_env, log):
    """Export, copy the usermod into the tree, write the env. Returns the
    env name to build."""
    out = project.export()
    src = os.path.join(out, USERMOD)
    dst = os.path.join(ROOT, "usermods", USERMOD)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    mods = usermods_of(base_env)
    if "cube_fx" in mods:
        # The effects register through cube_fx's bank; a second copy of the
        # bank's usermod would be the same class twice.
        for f in ("cube_fx_bank.cpp",):
            p = os.path.join(dst, f)
            if os.path.exists(p):
                os.remove(p)
        log(f"staged {USERMOD} beside cube_fx (its bank is shared; the effects take bank slots)")
    else:
        log(f"staged {USERMOD} with its own bank")
    env = "studio_" + base_env
    lines = [MARK_BEGIN, f"[env:{env}]", f"extends = env:{base_env}", "custom_usermods ="]
    lines += [f"  {m}" for m in mods if m != USERMOD] + [f"  {USERMOD}", MARK_END, ""]
    path = os.path.join(ROOT, "platformio_override.ini")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else "[platformio]\n"
    if MARK_BEGIN in text and MARK_END in text:
        a, b = text.index(MARK_BEGIN), text.index(MARK_END) + len(MARK_END)
        text = text[:a] + "\n".join(lines).rstrip("\n") + text[b:]
    else:
        text = text.rstrip("\n") + "\n\n" + "\n".join(lines)
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    log(f"environment [env:{env}] written to platformio_override.ini")
    # A new env fetches its libraries afresh from the registry. The base
    # env has them already: start from its copy, so the first build needs
    # no network and takes no longer than the base's would.
    src_deps = os.path.join(ROOT, ".pio", "libdeps", base_env)
    dst_deps = os.path.join(ROOT, ".pio", "libdeps", env)
    if os.path.isdir(src_deps) and not os.path.isdir(dst_deps):
        shutil.copytree(src_deps, dst_deps)
        log(f"libraries seeded from {base_env}")
    return env


def firmware_bin(env):
    return os.path.join(ROOT, ".pio", "build", env, "firmware.bin")


def upload(host, path, log, timeout=180):
    """POST the binary to /update. The device checks the subnet, its PIN
    and its OTA lock, and reboots on success."""
    host = (host or "").strip().rstrip("/")
    if not host:
        return False, "no device address"
    if not host.startswith("http"):
        host = "http://" + host
    data = open(path, "rb").read()
    boundary = "----studio" + str(int(time.time()))
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"update\"; filename=\"firmware.bin\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(host + "/update", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    log(f"sending {len(data) // 1024} KB to {host}/update ...")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            page = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        page = e.read().decode("utf-8", "replace")
        return False, f"the device answered {e.code}: " + _message(page)
    except Exception as e:
        return False, f"upload failed: {e}"
    return True, _message(page) or "sent - the device is rebooting"


def _message(page):
    """The text of WLED's message page, without its markup."""
    import re
    t = re.sub(r"<script.*?</script>", "", page, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(t.split())[:200]


def _get_json(host, path, timeout=5):
    import json
    with urllib.request.urlopen(host + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def push_settings(host, effect, params, palette, colours):
    """The current effect and its settings to the device's first segment
    over /json/state: the effect and palette found by NAME in the device's
    own lists (its ids are its own), the sliders, the checkboxes, the three
    colours. Returns (ok, message)."""
    import json
    host = (host or "").strip().rstrip("/")
    if not host:
        return False, "no device address"
    if not host.startswith("http"):
        host = "http://" + host
    try:
        names = _get_json(host, "/json/effects")
        pals = _get_json(host, "/json/palettes")
    except Exception as e:
        return False, f"could not read the device's lists: {e}"
    want = effect.split("@")[0].strip().lower()
    fx = next((i for i, n in enumerate(names) if str(n).split("@")[0].strip().lower() == want), None)
    if fx is None:
        return False, f"the device has no effect called {effect!r} - flash the firmware with it first"
    seg = {"id": 0, "fx": fx, "sx": int(params.get("sx", 128)), "ix": int(params.get("ix", 128)),
           "c1": int(params.get("c1", 128)), "c2": int(params.get("c2", 128)), "c3": int(params.get("c3", 16)),
           "o1": bool(params.get("o1")), "o2": bool(params.get("o2")), "o3": bool(params.get("o3")),
           "col": [[(c >> 16) & 255, (c >> 8) & 255, c & 255] for c in colours]}
    pal = next((i for i, n in enumerate(pals) if str(n).strip().lower() == (palette or "").strip().lower()), None)
    if pal is not None:
        seg["pal"] = pal
    body = json.dumps({"on": True, "seg": [seg]}).encode()
    req = urllib.request.Request(host + "/json/state", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
    except Exception as e:
        return False, f"the device refused the state: {e}"
    note = "" if pal is not None else f" (palette {palette!r} not on the device; left as is)"
    return True, f"{effect} with its settings sent to {host} as effect {fx}" + note


class Job:
    def __init__(self, project, base_env, host, build=True, upload=True):
        self.project, self.base_env, self.host = project, base_env, host
        self.build, self.upload = build, upload
        self.q = queue.Queue()
        self.done = False
        self.ok = False
        self.result = ""
        self.proc = None
        self._cancel = False

    def log(self, line):
        self.q.put(line)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self._cancel = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    @staticmethod
    def _diagnose(line):
        """The two ways a build of many effects fails, in plain words."""
        import re
        m = re.search(r"program size \((\d+) bytes\) is greater than maximum allowed \((\d+) bytes\)", line)
        if m:
            over = int(m.group(1)) - int(m.group(2))
            return (f"the firmware is {over // 1024} KB over this environment's app partition "
                    f"({int(m.group(2)) // 1024} KB). Take effects off the list (File > Remove from the "
                    "effects list; ~5 KB each), or build for an environment with a bigger partition "
                    "(esp32dev_16M, an S3 with 16 MB).")
        m = re.search(r"region `(\w+)' overflowed by (\d+) bytes", line)
        if m:
            return (f"the firmware needs {int(m.group(2)) // 1024} KB more RAM than the chip has ({m.group(1)}): "
                    "an effect keeps too much static state - fewer effects on the list, or fewer big "
                    "state nodes (Reaction diffusion, Shells) in them.")
        return None

    def _run(self):
        try:
            env = stage(self.project, self.base_env, self.log)
            if self.build:
                pio = pio_exe()
                if not pio:
                    self.result = "PlatformIO not found: install it (pip install platformio) or put pio on the path"
                    return
                self.log(f"{os.path.basename(pio)} run -e {env}   (in {ROOT})")
                t0 = time.time()
                flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
                self.proc = subprocess.Popen([pio, "run", "-e", env], cwd=ROOT, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                             bufsize=1, **flags)
                why = None
                for line in self.proc.stdout:
                    line = line.rstrip()
                    if line:
                        self.log(line)
                        why = why or self._diagnose(line)
                    if self._cancel:
                        break
                rc = self.proc.wait()
                if self._cancel:
                    self.result = "cancelled"; return
                if rc != 0:
                    self.result = why or f"build failed ({rc}) - the last lines above say why"; return
                self.log(f"built in {time.time() - t0:.0f} s")
            bin_ = firmware_bin(env)
            if not os.path.exists(bin_):
                self.result = f"no firmware at {bin_} - build first"; return
            self.log(f"firmware: {bin_} ({os.path.getsize(bin_) // 1024} KB)")
            if self.upload:
                ok, msg = upload(self.host, bin_, self.log)
                self.result = msg
                self.ok = ok
            else:
                self.result = "built; not sent"
                self.ok = True
        except Exception as e:
            self.result = f"failed: {e}"
        finally:
            self.done = True
