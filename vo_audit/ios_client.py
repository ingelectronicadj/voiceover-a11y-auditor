"""Cliente iOS / Xcode Simulator (xcrun simctl, parcheo automatico de .ipa para Apple Silicon y puente AXAudit)."""

import glob
import json
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
import time
from .config import SCRIPT_DIR


_PATCHED_IPA_CACHE = {}


class IosClient:
    """Encapsula todas las operaciones sobre xcrun simctl, instalacion de .ipa/.app y vo_bridge."""

    def __init__(self, device="booted", timeout=30):
        self.device = device or "booted"
        self.timeout = timeout
        self.device_name = ""
        self.os_version = ""

    def _simctl(self, args, check=False, timeout=None, raw=False):
        cmd = ["xcrun", "simctl"] + list(args)
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
            timeout=timeout or self.timeout,
        )
        return r.stdout if raw else r.stdout.decode("utf-8", "replace")

    def list_simulators(self):
        """Devuelve la lista de simuladores iOS disponibles con nombre, udid, estado y version de iOS."""
        raw = self._simctl(["list", "devices", "available", "-j"])
        data = json.loads(raw or "{}")
        out = []
        for runtime_id, devs in (data.get("devices") or {}).items():
            if "iOS" not in runtime_id:
                continue
            m_ver = re.search(r"iOS-(\d+-\d+)", runtime_id)
            ios_ver = m_ver.group(1).replace("-", ".") if m_ver else runtime_id.split(".")[-1]
            for d in devs:
                if not d.get("isAvailable", True):
                    continue
                out.append({
                    "name": d.get("name", ""),
                    "udid": d.get("udid", ""),
                    "state": d.get("state", "Shutdown"),
                    "ios_version": ios_ver,
                })
        out.sort(key=lambda x: (x["state"] == "Booted", x["ios_version"], x["name"]), reverse=True)
        return out

    def ensure_simulator_running(self, sim_name_or_udid=None, boot_timeout=90):
        """Asegura que el simulador objetivo este encendido (Booted) y resuelve su UDID real."""
        target = (sim_name_or_udid or self.device or "booted").strip()
        sims = self.list_simulators()
        if not sims:
            raise RuntimeError("No se encontraron simuladores iOS disponibles en Xcode (xcrun simctl list).")

        chosen = None
        if target.lower() == "booted":
            booted = [s for s in sims if s["state"] == "Booted"]
            if booted:
                chosen = booted[0]
            else:
                iphones = [s for s in sims if "iPhone" in s["name"]]
                chosen = iphones[0] if iphones else sims[0]
        else:
            t_norm = target.lower().replace("xr", "xʀ")
            for s in sims:
                if s["udid"].lower() == target.lower():
                    chosen = s
                    break
            if not chosen:
                exact_matches = [
                    s for s in sims
                    if s["name"].lower() == target.lower() or s["name"].lower() == t_norm
                ]
                matches = exact_matches or [
                    s for s in sims
                    if target.lower() in s["name"].lower() or t_norm in s["name"].lower()
                ]
                if matches:
                    booted_m = [s for s in matches if s["state"] == "Booted"]
                    chosen = booted_m[0] if booted_m else matches[0]

        if not chosen:
            raise RuntimeError("No se encontró ningún simulador iOS que coincida con '%s'." % target)

        self.device = chosen["udid"]
        self.device_name = chosen["name"]
        self.os_version = chosen["ios_version"]

        if chosen["state"] != "Booted":
            print("      [simulador] iniciando '%s' (iOS %s, %s)..." % (chosen["name"], chosen["ios_version"], chosen["udid"]))
            self._simctl(["boot", self.device], check=False, timeout=boot_timeout)
            self._simctl(["bootstatus", self.device, "-b"], check=False, timeout=boot_timeout)
            time.sleep(2.5)
        return self.device

    def preflight_check(self):
        """Devuelve metadatos del simulador activo (UDID, modelo, version de iOS, locale)."""
        if not self.device_name or self.device == "booted":
            self.ensure_simulator_running()
        loc = self._simctl(["spawn", self.device, "defaults", "read", "Apple Global Domain", "AppleLocale"]).strip()
        if not loc or "does not exist" in loc:
            loc = "es_AR"
        return {
            "device": self.device,
            "name": self.device_name or "iPhone Simulator",
            "sdk": "iOS %s" % (self.os_version or "?"),
            "locale": loc.replace("_", "-"),
        }

    def ensure_locale(self, target_locale):
        """Configura el idioma y region preferidos en el simulador iOS (ej. 'es-AR' o 'en-US')."""
        if not target_locale:
            return None
        lang = target_locale.replace("_", "-")
        apple_loc = target_locale.replace("-", "_")
        self._simctl(["spawn", self.device, "defaults", "write", "Apple Global Domain", "AppleLanguages", "-array", lang])
        self._simctl(["spawn", self.device, "defaults", "write", "Apple Global Domain", "AppleLocale", "-string", apple_loc])
        return lang

    def list_installed_apps(self):
        """Lista los bundleIdentifiers de las aplicaciones de usuario instaladas en el simulador."""
        out = self._simctl(["listapps", self.device])
        # Extraer CFBundleIdentifier de aplicaciones User
        bundles = []
        for m in re.finditer(r'"([a-zA-Z0-9_.-]+)"\s*=\s*\{(.*?)\n\s*\};', out, re.S):
            bid, body = m.group(1), m.group(2)
            if "com.apple." in bid:
                continue
            bundles.append(bid)
        return sorted(set(bundles))

    def get_foreground_package(self):
        """Detecta la app de usuario actualmente en ejecucion en el simulador."""
        apps = self.list_installed_apps()
        ps_out = self._simctl(["spawn", self.device, "launchctl", "list"])
        for bid in apps:
            if bid in ps_out:
                return bid, "UIApplication"
        return (apps[0], "UIApplication") if apps else ("", "")

    def install_app_or_ipa(self, path):
        """Instala un paquete .app o .ipa en el simulador iOS.
        Si recibe un .ipa compilado para dispositivo fisico (PLATFORM_IOS arm64), parchea automaticamente
        sus cabeceras Mach-O LC_BUILD_VERSION a IOSSIMULATOR con vtool y lo re-firma ad-hoc para correr en el Simulador."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(abs_path):
            raise RuntimeError("No se encontró el archivo o paquete: %s" % abs_path)

        if abs_path in _PATCHED_IPA_CACHE:
            cached_dir, cached_bid = _PATCHED_IPA_CACHE[abs_path]
            if os.path.isdir(cached_dir):
                self._simctl(["install", self.device, cached_dir], check=True, timeout=180)
                print("      [ipa] instalado desde caché en %s -> bundleId: %s" % (self.device_name or self.device, cached_bid))
                return cached_bid

        if abs_path.endswith(".app") and os.path.isdir(abs_path):
            return self._patch_and_install_app_bundle(abs_path, in_place=False, cache_key=abs_path)

        print("      [ipa] extrayendo y adaptando %s para iOS Simulator..." % os.path.basename(abs_path))
        tmp_dir = tempfile.mkdtemp(prefix="vo_ipa_")
        subprocess.run(["unzip", "-q", abs_path, "-d", tmp_dir], check=True, timeout=120)
        apps = glob.glob(os.path.join(tmp_dir, "Payload", "*.app"))
        if not apps:
            apps = glob.glob(os.path.join(tmp_dir, "**", "*.app"), recursive=True)
        if not apps:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError("No se encontró ningún paquete .app dentro de %s" % abs_path)
        return self._patch_and_install_app_bundle(apps[0], in_place=True, cache_key=abs_path)

    def _patch_and_install_app_bundle(self, app_dir, in_place=False, cache_key=None):
        work_app = app_dir
        if not in_place:
            tmp_parent = tempfile.mkdtemp(prefix="vo_app_")
            work_app = os.path.join(tmp_parent, os.path.basename(app_dir))
            shutil.copytree(app_dir, work_app)
        info_path = os.path.join(work_app, "Info.plist")
        with open(info_path, "rb") as fp:
            info = plistlib.load(fp)
        bundle_id = info.get("CFBundleIdentifier", "")
        exec_name = info.get("CFBundleExecutable", "")
        min_os = info.get("MinimumOSVersion", "15.0")

        prov = os.path.join(work_app, "embedded.mobileprovision")
        if os.path.exists(prov):
            os.remove(prov)

        for root, _, files in os.walk(work_app):
            for fn in files:
                if fn == "Info.plist":
                    p = os.path.join(root, fn)
                    try:
                        with open(p, "rb") as fp:
                            d = plistlib.load(fp)
                        if "CFBundleSupportedPlatforms" in d:
                            d["CFBundleSupportedPlatforms"] = ["iPhoneSimulator"]
                        if "DTPlatformName" in d:
                            d["DTPlatformName"] = "iphonesimulator"
                        with open(p, "wb") as fp:
                            plistlib.dump(d, fp)
                    except Exception:
                        pass

        binaries = []
        main_bin = os.path.join(work_app, exec_name)
        if os.path.isfile(main_bin):
            self._neutralize_simulator_jailbreak_checks(main_bin)
            binaries.append(main_bin)
        for fw in glob.glob(os.path.join(work_app, "Frameworks", "*.framework")):
            fw_name = os.path.splitext(os.path.basename(fw))[0]
            b = os.path.join(fw, fw_name)
            if os.path.isfile(b):
                binaries.append(b)

        for b in binaries:
            subprocess.run(
                [
                    "vtool", "-arch", "arm64",
                    "-set-build-version", "iossim", min_os, "26.5",
                    "-replace", "-output", b, b,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            subprocess.run(
                ["codesign", "-f", "-s", "-", b],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

        subprocess.run(
            ["codesign", "-f", "-s", "-", "--deep", work_app],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        if cache_key:
            _PATCHED_IPA_CACHE[cache_key] = (work_app, bundle_id)
        self._simctl(["install", self.device, work_app], check=True, timeout=180)
        print("      [ipa] instalado correctamente en %s -> bundleId: %s" % (self.device_name or self.device, bundle_id))
        return bundle_id

    @staticmethod
    def _neutralize_simulator_jailbreak_checks(bin_path):
        """Neutraliza detectores de rutas de sistema pensados para dispositivo fisico (/bin/bash, Cydia)
        que producen falsos positivos en macOS iOS Simulator."""
        import struct

        try:
            data = bytearray(open(bin_path, "rb").read())
            modified = False
            for old_s, new_s in (
                (b"/bin/bash\x00", b"/nonexist\x00"),
                (b"/usr/sbin/sshd\x00", b"/nonexist/sshd\x00"),
                (b"/etc/apt\x00", b"/nonexis\x00"),
                (b"/Applications/Cydia.app\x00", b"/Applications/NoApp.app\x00"),
            ):
                if old_s in data:
                    data = data.replace(old_s, new_s)
                    modified = True

            sig1 = bytes.fromhex("080040391f050071c10a0054")
            idx1 = data.find(sig1)
            if idx1 != -1:
                struct.pack_into("<I", data, idx1, 0xD65F03C0)
                modified = True

            sig2 = bytes.fromhex("6a010a2a4901092a2901001209010039")
            idx2 = data.find(sig2)
            if idx2 != -1:
                struct.pack_into("<I", data, idx2 + 8, 0x52800009)
                modified = True

            if modified:
                with open(bin_path, "wb") as fp:
                    fp.write(data)
        except Exception:
            pass

    def ensure_app_installed(self, bundle_id):
        """Verifica si bundle_id esta instalado en este simulador; si falta, lo clona automaticamente de otro simulador local."""
        if not bundle_id:
            return False
        cur = self._simctl(["get_app_container", self.device, bundle_id, "app"], check=False).strip()
        if cur and os.path.isdir(cur):
            return True
        sim_root = os.path.expanduser("~/Library/Developer/CoreSimulator/Devices")
        for app_cand in glob.glob(os.path.join(sim_root, "*", "data", "Containers", "Bundle", "Application", "*", "*.app")):
            plist_p = os.path.join(app_cand, "Info.plist")
            if not os.path.isfile(plist_p):
                continue
            try:
                with open(plist_p, "rb") as fp:
                    info = plistlib.load(fp)
                if info.get("CFBundleIdentifier") == bundle_id:
                    print("      [preflight] instalando %s (%s) en %s..." % (os.path.basename(app_cand), bundle_id, self.device_name or self.device))
                    self._simctl(["install", self.device, app_cand], check=False, timeout=120)
                    return True
            except Exception:
                continue
        return False

    def ensure_app_foreground(self, bundle_id, relaunch=False):
        if not bundle_id:
            return
        self.ensure_app_installed(bundle_id)
        if relaunch:
            self._simctl(["terminate", self.device, bundle_id], check=False)
            time.sleep(0.8)
        self._simctl(["launch", self.device, bundle_id], check=False)
        time.sleep(6.0)

    def screencap_png(self, path):
        self._simctl(["io", self.device, "screenshot", path], check=False)
        return path

    def ensure_bridge_binary(self):
        src = os.path.join(SCRIPT_DIR, "vo_bridge.swift")
        binpath = os.path.join(SCRIPT_DIR, "vo_bridge")
        if os.path.exists(binpath) and os.path.getmtime(binpath) >= os.path.getmtime(src):
            return binpath
        subprocess.run(["swiftc", "-O", src, "-o", binpath], check=True, capture_output=True, timeout=120)
        return binpath

    def reset_overlay(self):
        binpath = self.ensure_bridge_binary()
        subprocess.run(
            [binpath, "reset-overlay", "--udid", self.device],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )

    def tap_accessible_element(self, match_text=None, norm_coord=None):
        binpath = self.ensure_bridge_binary()
        cmd = [binpath, "tap-element", "--udid", self.device]
        if norm_coord and len(norm_coord) == 2:
            cmd += ["--coord", "%s,%s" % (norm_coord[0], norm_coord[1])]
        elif match_text:
            cmd += ["--match", str(match_text)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        try:
            return json.loads((res.stdout or "{}").strip().splitlines()[-1])
        except Exception:
            return {"ok": False}

    def run_bridge_walk(self, out_dir, max_steps=80, delay=0.75, backward=False, test_modals=False):
        """Ejecuta el barrido lineal de VoiceOver via vo_bridge (XDMDeviceSIM + AXAuditInspectorFocus)."""
        binpath = self.ensure_bridge_binary()
        cmd = [
            binpath,
            "walk",
            "--udid", self.device,
            "--steps", str(int(max_steps)),
            "--delay", str(float(delay)),
            "--out-dir", out_dir,
        ]
        if backward:
            cmd.append("--backward")
        if test_modals:
            cmd.append("--test-modals")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Reenviar logs de paso en stderr ignorando avisos de clases duplicadas de Xcode
        for err_line in proc.stderr:
            if "implemented in both" in err_line or err_line.startswith("objc["):
                continue
            print(err_line, end="")
        stdout_data = proc.stdout.read()
        proc.wait(timeout=max(120, int(max_steps * (delay + 2.0))))
        lines = [ln.strip() for ln in (stdout_data or "").splitlines() if ln.strip().startswith("{")]
        if not lines:
            return [], [], set()
        payload = json.loads(lines[-1])
        steps = payload.get("steps") or []
        tree_nodes = payload.get("tree_nodes") or []
        visited = set()
        for s in steps:
            n = s.get("node")
            if isinstance(n, dict):
                b = tuple(n["bounds"]) if n.get("bounds") else None
                n["bounds"] = b
                visited.add((n.get("text", ""), n.get("desc", ""), n.get("cls", ""), b))
        for n in tree_nodes:
            if isinstance(n, dict) and n.get("bounds"):
                n["bounds"] = tuple(n["bounds"])
        return steps, tree_nodes, visited
