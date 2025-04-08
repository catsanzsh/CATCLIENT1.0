import traceback
import os
import sys
import json
import shutil
import zipfile
import threading
import urllib.request
import urllib.error
import ssl
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re
import subprocess
import uuid as uuidlib
import platform

# ----------------------------------------------------------------------------------
#                           CROSS-PLATFORM MINECRAFT DIR
# ----------------------------------------------------------------------------------

def get_mc_dir():
    """
    Returns the default Minecraft directory based on the current OS.
    """
    os_name = platform.system()
    if os_name == 'Windows':
        # Standard on Windows: %APPDATA%\.minecraft
        return os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), '.minecraft')
    elif os_name == 'Darwin':
        # Standard on macOS
        return os.path.expanduser('~/Library/Application Support/minecraft')
    else:
        # Linux, BSD, or other Unix-likes
        return os.path.expanduser('~/.minecraft')

# ----------------------------------------------------------------------------------
#                               GLOBAL CONSTANTS
# ----------------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (Macintosh; Apple Silicon Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36"
LUNAR_API_BASE = "https://api.lunarclientprod.com"
LUNAR_COSMETICS_ENDPOINT = f"{LUNAR_API_BASE}/launcher/cosmetics/users"
TLAUNCHER_SKIN_API = "https://auth.tlauncher.org/skin/"
VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
ASSET_BASE_URL = "https://resources.download.minecraft.net/"
LIBRARIES_BASE_URL = "https://libraries.minecraft.net/"
FORGE_MAVEN_URL = "https://maven.minecraftforge.net/"

# Determine the OS once
IS_MAC = (platform.system() == 'Darwin')

# ----------------------------------------------------------------------------------
#                             SSL CONTEXT & RELATED
# ----------------------------------------------------------------------------------

def get_ssl_context(verify=False):
    return ssl.create_default_context() if verify else ssl._create_unverified_context()

# ----------------------------------------------------------------------------------
#                          PLATFORM-SPECIFIC DETECTIONS
# ----------------------------------------------------------------------------------

def is_arm64():
    """Detect if we're on an ARM64 architecture (e.g., Apple Silicon)."""
    return platform.machine().lower() in ('arm64', 'aarch64')

def detect_rosetta():
    """
    Returns True if we're on macOS Apple Silicon *and* running under Rosetta 2.
    If not macOS or check fails, returns False.
    """
    if not IS_MAC:
        return False
    try:
        result = subprocess.run(['sysctl', '-n', 'sysctl.proc_translated'],
                                capture_output=True, text=True)
        return result.stdout.strip() == '1'
    except:
        return False

def run_with_rosetta(cmd):
    """
    If on macOS ARM and not under Rosetta, prepend 'arch -x86_64' to the cmd.
    Otherwise, returns cmd unchanged.
    """
    if IS_MAC and is_arm64() and not detect_rosetta():
        return ['arch', '-x86_64'] + cmd
    return cmd

# ----------------------------------------------------------------------------------
#                     DIRECTORIES AND GLOBAL STATE INITIALIZATION
# ----------------------------------------------------------------------------------

mc_dir = get_mc_dir()
os.makedirs(mc_dir, exist_ok=True)

VERSIONS_DIR = os.path.join(mc_dir, "versions")
ASSETS_DIR = os.path.join(mc_dir, "assets")
MODPACKS_DIR = os.path.join(mc_dir, "modpacks")
LIBRARIES_DIR = os.path.join(mc_dir, "libraries")
LUNAR_CACHE_DIR = os.path.join(mc_dir, "lunar_cache")
TLAUNCHER_SKINS_DIR = os.path.join(mc_dir, "tlauncher_skins")

for d in [
    VERSIONS_DIR,
    MODPACKS_DIR,
    os.path.join(ASSETS_DIR, "indexes"),
    os.path.join(ASSETS_DIR, "objects"),
    LIBRARIES_DIR,
    LUNAR_CACHE_DIR,
    TLAUNCHER_SKINS_DIR
]:
    os.makedirs(d, exist_ok=True)

# ----------------------------------------------------------------------------------
#                          ACCOUNTS & AUTH MANAGEMENT
# ----------------------------------------------------------------------------------

accounts = []
accounts_file = os.path.join(mc_dir, "launcher_accounts.json")
if os.path.isfile(accounts_file):
    try:
        with open(accounts_file, 'r') as f:
            accounts = json.load(f)
    except Exception as e:
        print(f"Warning: Error loading accounts: {e}")
        accounts = []

def save_accounts():
    try:
        with open(accounts_file, 'w') as f:
            json.dump(accounts, f, indent=4)
    except Exception as e:
        print(f"Error saving accounts: {e}")

def add_account(acc_type, email_username, password_token=None):
    if not email_username:
        return
    offline_uuid = str(uuidlib.uuid3(uuidlib.NAMESPACE_DNS, email_username))
    acc = {
        "type": acc_type,
        "username": email_username,
        "uuid": offline_uuid,
        "token": password_token or "null" if acc_type in ["tlauncher", "microsoft"] else "0",
        "client": "lunar" if acc_type == "lunar" else None
    }
    for i, existing_acc in enumerate(accounts):
        if existing_acc.get("type") == acc_type and existing_acc.get("username") == email_username:
            accounts[i] = acc
            save_accounts()
            print(f"Account '{email_username}' ({acc_type}) updated.")
            return
    accounts.append(acc)
    save_accounts()
    print(f"Account '{email_username}' ({acc_type}) added.")

# ----------------------------------------------------------------------------------
#                                COSMETICS
# ----------------------------------------------------------------------------------

def fetch_lunar_cosmetics(uuid, ssl_verify=False):
    cache_file = os.path.join(LUNAR_CACHE_DIR, f"{uuid}_cosmetics.json")
    if os.path.isfile(cache_file):
        with open(cache_file, 'r') as f:
            return json.load(f)

    headers = {"User-Agent": USER_AGENT}
    params = {"uuids": uuid}
    try:
        context = get_ssl_context(ssl_verify)
        req = urllib.request.Request(
            f"{LUNAR_COSMETICS_ENDPOINT}?{urllib.parse.urlencode(params)}", 
            headers=headers
        )
        with urllib.request.urlopen(req, context=context) as response:
            data = json.loads(response.read().decode())
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=4)
            return data
    except Exception as e:
        print(f"Failed to fetch Lunar cosmetics for UUID {uuid}: {e}")
        return {}

def fetch_tlauncher_skin(username, ssl_verify=False):
    skin_file = os.path.join(TLAUNCHER_SKINS_DIR, f"{username}_skin.png")
    cape_file = os.path.join(TLAUNCHER_SKINS_DIR, f"{username}_cape.png")
    if os.path.isfile(skin_file) and os.path.isfile(cape_file):
        return skin_file, cape_file

    skin_url = f"{TLAUNCHER_SKIN_API}{username}.png"
    cape_url = f"{TLAUNCHER_SKIN_API}cape/{username}.png"
    try:
        download_file(skin_url, skin_file, "TLauncher skin", ssl_verify)
    except Exception as e:
        print(f"Could not download TLauncher skin: {e}")
    try:
        download_file(cape_url, cape_file, "TLauncher cape", ssl_verify)
    except Exception as e:
        print(f"Could not download TLauncher cape: {e}")

    skin_exists = skin_file if os.path.isfile(skin_file) else None
    cape_exists = cape_file if os.path.isfile(cape_file) else None
    return skin_exists, cape_exists

def download_file(url, dest_path, description="file", ssl_verify=False):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        print(f"Downloading {description}: {os.path.basename(dest_path)} from {url}")
        with urllib.request.urlopen(req, context=get_ssl_context(ssl_verify)) as response, \
             open(dest_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        print(f"Finished downloading {os.path.basename(dest_path)}")
    except urllib.error.HTTPError as e:
        raise Exception(f"HTTP Error {e.code}: {e.reason}")
    except Exception as e:
        raise Exception(f"Failed to download {description} from {url}: {e}")

# ----------------------------------------------------------------------------------
#                            VERSION MANIFEST LOADING
# ----------------------------------------------------------------------------------

version_manifest_path = os.path.join(mc_dir, "version_manifest_v2.json")
all_versions = {}

def load_version_manifest(ssl_verify=False):
    global all_versions
    try:
        if not os.path.isfile(version_manifest_path):
            download_file(VERSION_MANIFEST_URL, version_manifest_path, "version manifest", ssl_verify)
        with open(version_manifest_path, 'r') as f:
            version_manifest = json.load(f)
        all_versions = {v['id']: v['url'] for v in version_manifest['versions']}
        return version_manifest
    except Exception as e:
        print(f"Error loading version manifest: {e}")
        return {"versions": []}

# ----------------------------------------------------------------------------------
#                           MINECRAFT INSTALLATION LOGIC
# ----------------------------------------------------------------------------------

def install_version(version_id, status_callback=None, ssl_verify=False):
    if status_callback:
        status_callback(f"Checking version: {version_id}...")

    version_folder = os.path.join(VERSIONS_DIR, version_id)
    version_json_path = os.path.join(version_folder, f"{version_id}.json")
    version_jar_path = os.path.join(version_folder, f"{version_id}.jar")

    if not os.path.isfile(version_json_path):
        if version_id not in all_versions:
            raise Exception(f"Version '{version_id}' not found in Mojang manifest.")
        version_url = all_versions[version_id]
        os.makedirs(version_folder, exist_ok=True)
        if status_callback:
            status_callback(f"Downloading version JSON for {version_id}...")
        download_file(version_url, version_json_path, f"version JSON ({version_id})", ssl_verify)

    with open(version_json_path, 'r') as f:
        version_data = json.load(f)

    parent_id = version_data.get("inheritsFrom")
    parent_data = {}
    if parent_id:
        if status_callback:
            status_callback(f"Version {version_id} inherits from {parent_id}. Installing parent...")
        install_version(parent_id, status_callback, ssl_verify)
        parent_json_path = os.path.join(VERSIONS_DIR, parent_id, f"{parent_id}.json")
        with open(parent_json_path, 'r') as pf:
            parent_data = json.load(pf)

    client_info = version_data.get("downloads", {}).get("client")
    if client_info and not os.path.isfile(version_jar_path):
        client_url = client_info.get("url")
        if client_url:
            if status_callback:
                status_callback(f"Downloading client JAR for {version_id}...")
            download_file(client_url, version_jar_path, f"client JAR ({version_id})", ssl_verify)

    libraries = version_data.get("libraries", []) + parent_data.get("libraries", [])
    for i, lib in enumerate(libraries):
        rules = lib.get("rules", [])
        # Only allow libs for the current OS or if no OS is specified in rules
        allowed = (
            not rules
            or any(
                (rule["action"] == "allow")
                and (
                    not rule.get("os")
                    or rule["os"].get("name") == ("osx" if IS_MAC else "windows" if platform.system() == "Windows" else "linux")
                )
                for rule in rules
            )
        )
        if not allowed:
            continue

        artifact = lib.get("downloads", {}).get("artifact")
        if artifact and artifact.get("path"):
            lib_path = os.path.join(LIBRARIES_DIR, artifact["path"])
            if not os.path.isfile(lib_path):
                lib_url = artifact.get("url") or (LIBRARIES_BASE_URL + artifact["path"])
                if status_callback:
                    status_callback(f"Downloading library {i+1}/{len(libraries)}: {os.path.basename(lib_path)}")
                download_file(lib_url, lib_path, f"library ({os.path.basename(lib_path)})", ssl_verify)

        natives_info = lib.get("natives")
        classifiers = lib.get("downloads", {}).get("classifiers", {})
        if natives_info and classifiers:
            # Choose a natives key based on OS/arch
            if IS_MAC and is_arm64() and 'natives-osx-arm64' in classifiers:
                native_key = 'natives-osx-arm64'
            else:
                # e.g. might be "natives-windows", "natives-linux", "natives-osx"
                native_key = natives_info.get('osx') if IS_MAC else natives_info.get('windows') if platform.system() == 'Windows' else natives_info.get('linux')
                # Some templates are like "natives-windows-%(arch)", so handle that:
                if native_key and isinstance(native_key, str):
                    native_key = native_key.replace("${arch}", "64")

            if native_key and native_key in classifiers:
                native_artifact = classifiers[native_key]
                native_path = os.path.join(LIBRARIES_DIR, native_artifact["path"])
                if not os.path.isfile(native_path):
                    native_url = native_artifact.get("url") or (LIBRARIES_BASE_URL + native_artifact["path"])
                    if status_callback:
                        status_callback(f"Downloading native library: {os.path.basename(native_path)}")
                    download_file(native_url, native_path, f"native library ({os.path.basename(native_path)})", ssl_verify)

                natives_dir = os.path.join(version_folder, "natives")
                os.makedirs(natives_dir, exist_ok=True)
                try:
                    with zipfile.ZipFile(native_path, 'r') as zf:
                        for member in zf.namelist():
                            if not member.startswith("META-INF/") and not member.endswith('/'):
                                zf.extract(member, natives_dir)
                except Exception as e:
                    print(f"Warning: Failed to extract native library {native_path}: {e}")

    asset_index_info = version_data.get("assetIndex") or parent_data.get("assetIndex")
    if asset_index_info:
        idx_id = asset_index_info["id"]
        idx_url = asset_index_info["url"]
        idx_dest = os.path.join(ASSETS_DIR, "indexes", f"{idx_id}.json")
        if not os.path.isfile(idx_dest):
            if status_callback:
                status_callback(f"Downloading asset index {idx_id}...")
            download_file(idx_url, idx_dest, f"asset index ({idx_id})", ssl_verify)

        with open(idx_dest, 'r') as f:
            idx_data = json.load(f)
        for asset_name, info in idx_data["objects"].items():
            hash_val = info.get("hash")
            if hash_val:
                subdir = hash_val[:2]
                asset_path = os.path.join(ASSETS_DIR, "objects", subdir, hash_val)
                if not os.path.isfile(asset_path):
                    if status_callback:
                        status_callback(f"Downloading asset: {asset_name}")
                    download_file(f"{ASSET_BASE_URL}{subdir}/{hash_val}", asset_path, f"asset ({hash_val[:8]})", ssl_verify)

    # Patch "skinVersion" in JSON if missing
    try:
        with open(version_json_path, 'r+') as vf:
            data = json.load(vf)
            if not data.get("skinVersion", False):
                data["skinVersion"] = True
                vf.seek(0)
                json.dump(data, vf, indent=4)
                vf.truncate()
                print(f"Patched {version_id}.json with skinVersion=true")
    except Exception as e:
        print(f"Warning: Could not set skinVersion in {version_id}.json - {e}")

    if status_callback:
        status_callback(f"Version {version_id} installation complete.")

# ----------------------------------------------------------------------------------
#                           LUNAR CLIENT & TLAUNCHER SETUP
# ----------------------------------------------------------------------------------

def setup_lunar_client(version_id, account, status_callback=None, ssl_verify=False):
    if account["type"] == "offline":
        if status_callback:
            status_callback("Skipping Lunar setup for offline mode.")
        return
    if status_callback:
        status_callback(f"Setting up Lunar Client for {version_id}...")

    lunar_dir = os.path.expanduser("~/.lunarclient")
    for d in [
        os.path.join(lunar_dir, "offline"),
        os.path.join(lunar_dir, "jre"),
        os.path.join(lunar_dir, "cosmetics")
    ]:
        os.makedirs(d, exist_ok=True)

    offline_marker = os.path.join(lunar_dir, "offline", ".offline")
    if not os.path.exists(offline_marker):
        with open(offline_marker, 'w') as f:
            f.write("1")

    # Attempt to symlink the versions dir into Lunar's directory
    lunar_versions_dir = os.path.join(lunar_dir, "game-versions")
    if not os.path.exists(lunar_versions_dir):
        try:
            os.symlink(VERSIONS_DIR, lunar_versions_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            # On some platforms, symlinks may require admin privileges or be disabled
            pass

    settings_path = os.path.join(lunar_dir, "settings.json")
    if not os.path.exists(settings_path):
        with open(settings_path, 'w') as f:
            json.dump({
                "gameDir": mc_dir,
                "jreDir": os.path.join(lunar_dir, "jre"),
                "lastVersion": version_id,
                "offline": True
            }, f, indent=4)

    cosmetics_data = fetch_lunar_cosmetics(account["uuid"], ssl_verify)
    if cosmetics_data.get("users"):
        user_cosmetics = cosmetics_data["users"].get(account["uuid"], {})
        cape = user_cosmetics.get("cape")
        if cape and cape.get("textureUrl"):
            cape_path = os.path.join(lunar_dir, "cosmetics", f"cape_{account['uuid']}.png")
            download_file(cape["textureUrl"], cape_path, "Lunar cape texture", ssl_verify)
            # Also store a copy in .minecraft/assets if wanted
            cape_asset_path = os.path.join(ASSETS_DIR, "objects", cape["hash"][:2], cape["hash"])
            os.makedirs(os.path.dirname(cape_asset_path), exist_ok=True)
            shutil.copy(cape_path, cape_asset_path)

    if status_callback:
        status_callback(f"Lunar Client setup complete for {version_id}")

def setup_tlauncher_cosmetics(account, status_callback=None, ssl_verify=False):
    if account["type"] == "offline":
        if status_callback:
            status_callback("Skipping TLauncher cosmetics for offline mode.")
        return
    if status_callback:
        status_callback(f"Setting up TLauncher cosmetics for {account['username']}...")
    skin_path, cape_path = fetch_tlauncher_skin(account["username"], ssl_verify)
    if skin_path:
        skin_asset_path = os.path.join(ASSETS_DIR, "objects", "skin", f"{account['uuid']}.png")
        os.makedirs(os.path.dirname(skin_asset_path), exist_ok=True)
        shutil.copy(skin_path, skin_asset_path)
    if cape_path:
        cape_asset_path = os.path.join(ASSETS_DIR, "objects", "cape", f"{account['uuid']}.png")
        os.makedirs(os.path.dirname(cape_asset_path), exist_ok=True)
        shutil.copy(cape_path, cape_asset_path)
    if status_callback:
        status_callback(f"TLauncher cosmetics setup complete for {account['username']}")

# ----------------------------------------------------------------------------------
#                                GAME LAUNCH LOGIC
# ----------------------------------------------------------------------------------

def launch_game(
    version_id,
    account,
    ram_mb=1024,
    java_path="java",
    game_dir=None,
    server_ip=None,
    port=None,
    status_callback=None,
    use_rosetta=False,
    lunar_client=False,
    ssl_verify=False
):
    if status_callback:
        status_callback(f"Preparing to launch {version_id}...")

    effective_game_dir = game_dir or mc_dir

    if lunar_client:
        setup_lunar_client(version_id, account, status_callback, ssl_verify)
    if account["type"] == "tlauncher":
        setup_tlauncher_cosmetics(account, status_callback, ssl_verify)

    # Ensure the version is installed
    install_version(version_id, status_callback, ssl_verify)

    version_folder = os.path.join(VERSIONS_DIR, version_id)
    version_json_path = os.path.join(version_folder, f"{version_id}.json")
    with open(version_json_path, 'r') as f:
        vdata = json.load(f)

    main_class = vdata.get("mainClass")
    classpath = set()
    natives_dir_absolute = os.path.abspath(os.path.join(version_folder, "natives"))
    parent_data = {}
    if vdata.get("inheritsFrom"):
        parent_json_path = os.path.join(VERSIONS_DIR, vdata["inheritsFrom"], f"{vdata['inheritsFrom']}.json")
        with open(parent_json_path, 'r') as pf:
            parent_data = json.load(pf)
        main_class = main_class or parent_data.get("mainClass")

    def lib_rules_allow(lib):
        rules = lib.get("rules", [])
        return (
            not rules
            or any(
                (rule["action"] == "allow")
                and (
                    not rule.get("os")
                    or rule["os"].get("name") == ("osx" if IS_MAC else "windows" if platform.system() == "Windows" else "linux")
                )
                for rule in rules
            )
        )

    for lib in vdata.get("libraries", []) + parent_data.get("libraries", []):
        if lib_rules_allow(lib):
            artifact = lib.get("downloads", {}).get("artifact")
            if artifact and artifact.get("path"):
                lib_file = os.path.join(LIBRARIES_DIR, artifact["path"])
                if os.path.isfile(lib_file):
                    classpath.add(os.path.abspath(lib_file))

    version_jar_path = os.path.join(version_folder, f"{version_id}.jar")
    if os.path.isfile(version_jar_path):
        classpath.add(os.path.abspath(version_jar_path))
    elif vdata.get("inheritsFrom"):
        parent_jar_path = os.path.join(VERSIONS_DIR, vdata["inheritsFrom"], f"{vdata['inheritsFrom']}.jar")
        if os.path.isfile(parent_jar_path):
            classpath.add(os.path.abspath(parent_jar_path))

    jvm_args = [
        f"-Xmx{ram_mb}M",
        f"-Djava.library.path={natives_dir_absolute}"
    ]
    if is_arm64():
        jvm_args.extend([
            "-XX:+UseG1GC",
            "-XX:MaxGCPauseMillis=200",
            "-XX:ParallelGCThreads=4",
            "-Dapple.awt.application.name=Cat Client"
        ])
    if lunar_client:
        jvm_args.extend([
            "-Dfml.ignoreInvalidMinecraftCertificates=true",
            "-Dorg.lwjgl.opengl.Display.allowSoftwareOpenGL=true"
        ])
        # If the main class is the normal MC entrypoint, override with Lunar's
        if main_class and "net.minecraft.client.main.Main" in main_class:
            main_class = "com.moonsworth.lunar.genesis.Genesis"

    args_data = vdata.get("arguments", {})
    parent_args_data = parent_data.get("arguments", {})
    raw_jvm_args = args_data.get("jvm", parent_args_data.get("jvm", []))
    raw_game_args = args_data.get("game", parent_args_data.get("game", []))

    if not raw_game_args and "minecraftArguments" in vdata:
        raw_game_args = vdata["minecraftArguments"].split()

    replacements = {
        "auth_player_name": account["username"],
        "version_name": version_id,
        "game_directory": effective_game_dir,
        "assets_root": os.path.abspath(ASSETS_DIR),
        "assets_index_name": (vdata.get("assetIndex") or parent_data.get("assetIndex", {})).get("id", "legacy"),
        "auth_uuid": account["uuid"],
        "auth_access_token": account["token"],
        "user_type": "msa" if account["type"] == "microsoft" else "legacy",
        "version_type": vdata.get("type", "release"),
        "natives_directory": natives_dir_absolute,
        "classpath_separator": os.pathsep,
        "launcher_name": "LunarClient" if lunar_client else "CatClient",
        "launcher_version": "0.1.0"
    }

    # Process JVM args
    for arg in raw_jvm_args:
        if isinstance(arg, str):
            try:
                # Only replace placeholders present in the string
                jvm_args.append(arg.format(**{k: v for k, v in replacements.items() if k in arg}))
            except KeyError as e:
                print(f"Warning: Skipping JVM arg with unknown placeholder: {e}")
        elif isinstance(arg, dict) and any(r["action"] == "allow" for r in arg.get("rules", [])):
            value = arg["value"]
            try:
                if isinstance(value, list):
                    for v in value:
                        jvm_args.append(v.format(**replacements))
                else:
                    jvm_args.append(value.format(**replacements))
            except KeyError as e:
                print(f"Warning: Skipping JVM arg with unknown placeholder: {e}")

    jvm_args.extend(["-cp", os.pathsep.join(classpath)])

    # Process game args
    game_args = []
    for arg in raw_game_args:
        if isinstance(arg, str):
            try:
                game_args.append(arg.format(**{k: v for k, v in replacements.items() if k in arg}))
            except KeyError as e:
                print(f"Warning: Skipping game arg with unknown placeholder: {e}")
        elif isinstance(arg, dict) and "value" in arg:
            try:
                value = arg["value"]
                if isinstance(value, list):
                    for v in value:
                        game_args.append(v.format(**replacements))
                else:
                    game_args.append(value.format(**replacements))
            except KeyError as e:
                print(f"Warning: Skipping game arg with unknown placeholder: {e}")

    if server_ip:
        game_args.extend(["--server", server_ip])
        if port:
            game_args.extend(["--port", str(port)])

    command = [java_path] + jvm_args + [main_class] + game_args
    if use_rosetta and IS_MAC:
        command = run_with_rosetta(command)
    elif use_rosetta and not IS_MAC:
        # On non-macOS platforms, Rosetta doesn't exist; just ignore the flag
        pass

    if status_callback:
        status_callback(f"Launching Minecraft {version_id}...")
    try:
        subprocess.Popen(command, cwd=effective_game_dir)
        if status_callback:
            status_callback(f"Launched {version_id} successfully!")
    except Exception as e:
        raise Exception(f"Failed to launch game: {e}")

# ----------------------------------------------------------------------------------
#                                 TKINTER GUI
# ----------------------------------------------------------------------------------

class M1LauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Cat Client v0.1.0 [C] Team Flames [C] 2023 - 2026")
        self.root.geometry("650x680")

        self.version_manifest = {"versions": []}
        self.ssl_verify_var = tk.BooleanVar(value=False)

        # ========================= SSL FRAME =========================
        ssl_frame = ttk.LabelFrame(root, text="SSL Configuration")
        ssl_frame.pack(fill="x", padx=10, pady=5)

        ttk.Checkbutton(
            ssl_frame,
            text="Verify SSL Certificates (Disable if you have SSL errors)",
            variable=self.ssl_verify_var
        ).grid(row=0, column=0, sticky="w", padx=5, pady=2)

        ttk.Button(
            ssl_frame,
            text="Load Version Manifest",
            command=self.load_manifest
        ).grid(row=0, column=1, padx=5, pady=2)

        ttk.Label(
            ssl_frame,
            text=(
                "Note: On some systems, Python may have SSL certificate issues. "
                "If downloads fail, uncheck this option."
            ),
            wraplength=500,
            foreground="red"
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # ========================= PLATFORM FRAME =========================
        m1_frame = ttk.LabelFrame(root, text="Platform/Architecture Configuration")
        m1_frame.pack(fill="x", padx=10, pady=5)

        self.use_rosetta_var = tk.BooleanVar(value=False)
        self.use_rosetta_check = ttk.Checkbutton(
            m1_frame,
            text="Use Rosetta 2 (macOS Apple Silicon only)",
            variable=self.use_rosetta_var
        )
        self.use_rosetta_check.grid(row=0, column=0, sticky="w", padx=5, pady=2)

        self.lunar_client_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            m1_frame,
            text="Lunar Client Compatibility Mode",
            variable=self.lunar_client_var
        ).grid(row=1, column=0, sticky="w", padx=5, pady=2)

        arch_label = (
            "Apple Silicon (ARM64)" if is_arm64() else
            "Intel/Rosetta (x86_64)" if IS_MAC else
            f"{platform.system()} {platform.machine()}"
        )
        ttk.Label(
            m1_frame,
            text=f"Detected CPU architecture: {arch_label}"
        ).grid(row=2, column=0, sticky="w", padx=5, pady=2)

        rosetta_label = "N/A (non-macOS)"  
        if IS_MAC:
            rosetta_label = (
                "Yes (active)" if detect_rosetta() else
                "Installed, not active" if is_arm64() else
                "N/A (Intel Mac)"
            )
        ttk.Label(
            m1_frame,
            text=f"Rosetta 2: {rosetta_label}"
        ).grid(row=3, column=0, sticky="w", padx=5, pady=2)

        # Disable the rosetta checkbox if not macOS
        if not IS_MAC:
            self.use_rosetta_var.set(False)
            self.use_rosetta_check.state(["disabled"])

        # ========================= ACCOUNTS FRAME =========================
        acct_frame = ttk.LabelFrame(root, text="Accounts")
        acct_frame.pack(fill="x", padx=10, pady=5)

        self.acct_type_var = tk.StringVar(value="tlauncher")
        ttk.Radiobutton(acct_frame, text="TLauncher", variable=self.acct_type_var, value="tlauncher").grid(row=0, column=0, sticky="w", padx=5)
        ttk.Radiobutton(acct_frame, text="Offline",   variable=self.acct_type_var, value="offline").grid(row=0, column=1, sticky="w", padx=5)
        ttk.Radiobutton(acct_frame, text="Lunar",     variable=self.acct_type_var, value="lunar").grid(row=0, column=2, sticky="w", padx=5)
        ttk.Radiobutton(
            acct_frame,
            text="Microsoft (Demo)",
            variable=self.acct_type_var,
            value="microsoft",
            state="disabled"
        ).grid(row=0, column=3, sticky="w", padx=5)

        ttk.Label(acct_frame, text="Username/Email:").grid(row=1, column=0, padx=5, pady=3, sticky="e")
        self.username_entry = ttk.Entry(acct_frame, width=30)
        self.username_entry.grid(row=1, column=1, columnspan=2, padx=5, pady=3, sticky="we")

        ttk.Label(acct_frame, text="Password/Token:").grid(row=2, column=0, padx=5, pady=3, sticky="e")
        self.password_entry = ttk.Entry(acct_frame, width=30, show="*")
        self.password_entry.grid(row=2, column=1, columnspan=2, padx=5, pady=3, sticky="we")

        ttk.Label(acct_frame, text="(Optional for Offline/Lunar, Needed for TLauncher)").grid(row=3, column=1, columnspan=2, sticky="w", padx=5)
        ttk.Label(acct_frame, text="(Warning: Passwords stored insecurely)", foreground="orange").grid(row=4, column=1, columnspan=2, sticky="w", padx=5)

        ttk.Button(acct_frame, text="Add / Update Account", command=self.on_add_account).grid(row=1, column=3, rowspan=2, padx=10, pady=5, sticky="ns")

        ttk.Separator(acct_frame, orient='horizontal').grid(row=5, column=0, columnspan=4, sticky="ew", pady=10)

        ttk.Label(acct_frame, text="Select Account:").grid(row=6, column=0, padx=5, pady=5, sticky="e")
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(acct_frame, textvariable=self.account_var, state="readonly", width=40)
        self.account_combo.grid(row=6, column=1, columnspan=3, padx=5, pady=5, sticky="we")

        acct_frame.columnconfigure(1, weight=1)
        acct_frame.columnconfigure(2, weight=1)

        # ========================= VERSION FRAME =========================
        ver_frame = ttk.LabelFrame(root, text="Game Version / Modpack")
        ver_frame.pack(fill="x", padx=10, pady=5)

        self.version_var = tk.StringVar()
        self.version_combo = ttk.Combobox(ver_frame, textvariable=self.version_var, values=[], state="readonly", width=50)
        self.version_combo.grid(row=0, column=0, padx=5, pady=5, sticky="we")
        ver_frame.columnconfigure(0, weight=1)

        # ========================= LAUNCH OPTIONS FRAME =========================
        options_frame = ttk.LabelFrame(root, text="Launch Options")
        options_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(options_frame, text="Max RAM (MB):").grid(row=0, column=0, padx=5, pady=3, sticky="e")
        self.ram_spin = ttk.Spinbox(options_frame, from_=512, to=32768, increment=512, width=10)
        self.ram_spin.set("4096")
        self.ram_spin.grid(row=0, column=1, pady=3, sticky="w")

        ttk.Label(options_frame, text="Java Path:").grid(row=1, column=0, padx=5, pady=3, sticky="e")
        self.java_entry = ttk.Entry(options_frame, width=40)
        self.java_entry.insert(0, self.find_java())
        self.java_entry.grid(row=1, column=1, padx=5, pady=3, sticky="we")
        ttk.Button(options_frame, text="Browse...", command=self.browse_java).grid(row=1, column=2, padx=5)

        ttk.Label(options_frame, text="Server IP (Optional):").grid(row=2, column=0, padx=5, pady=3, sticky="e")
        self.server_entry = ttk.Entry(options_frame, width=30)
        self.server_entry.grid(row=2, column=1, padx=5, pady=3, sticky="w")

        ttk.Label(options_frame, text="Port:").grid(row=2, column=2, padx=2, pady=3, sticky="e")
        self.port_entry = ttk.Entry(options_frame, width=8)
        self.port_entry.grid(row=2, column=3, padx=5, pady=3, sticky="w")

        options_frame.columnconfigure(1, weight=1)

        # ========================= STATUS BAR =========================
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Frame(root, relief=tk.SUNKEN, padding="2 2 2 2")
        status_bar.pack(side=tk.BOTTOM, fill="x")
        ttk.Label(status_bar, textvariable=self.status_var).pack(side=tk.LEFT)

        # ========================= LAUNCH BUTTON =========================
        launch_frame = ttk.Frame(root)
        launch_frame.pack(pady=15)
        self.launch_btn = ttk.Button(launch_frame, text="Launch Game", command=self.on_launch, style="Accent.TButton")
        self.launch_btn.pack(ipadx=20, ipady=10)

        # ========================= STYLING =========================
        style = ttk.Style()
        # Attempt 'aqua' theme on macOS, otherwise fallback
        try:
            if IS_MAC:
                style.theme_use('aqua')
            else:
                style.theme_use(style.theme_use())  # Keep the default on other systems
        except tk.TclError:
            # If 'aqua' not available, just continue with the system default
            pass

        style.configure("Accent.TButton", font=('Helvetica', 12, 'bold'))

        # Initialize accounts and version data
        self.refresh_account_list()
        self.load_manifest()

    # --------------------------- LOADING & POPULATING VERSIONS ---------------------------

    def load_manifest(self):
        self.set_status("Loading version manifest...", "blue")
        try:
            self.version_manifest = load_version_manifest(self.ssl_verify_var.get())
            self.populate_version_list()
            self.set_status("Version manifest loaded successfully.", "green")
        except Exception as e:
            messagebox.showerror(
                "Error",
                f"Failed to load version manifest: {e}\n\n"
                "Try unchecking 'Verify SSL Certificates' if you suspect SSL issues."
            )
            self.set_status(f"Error loading manifest: {e}", "red")

    def populate_version_list(self):
        try:
            release_versions = sorted(
                [v['id'] for v in self.version_manifest['versions'] if v['type'] == 'release'],
                reverse=True
            )
            snapshot_versions = sorted(
                [v['id'] for v in self.version_manifest['versions'] if v['type'] == 'snapshot'],
                reverse=True
            )
            custom_versions = [
                item for item in os.listdir(VERSIONS_DIR)
                if os.path.isdir(os.path.join(VERSIONS_DIR, item)) and item not in all_versions
            ]
            self.popular_modpacks = {
                "RLCraft (Modpack)": "rlcraft",
                "All the Mods 9 (Modpack)": "all-the-mods-9-atm9",
                "Pixelmon Modpack (Modpack)": "the-pixelmon-modpack",
                "One Block MC (Modpack)": "one-block-mc",
                "DawnCraft (Modpack)": "dawncraft",
                "Better MC (Modpack)": "better-mc-bmc1-forge",
            }
            modpack_names = sorted(self.popular_modpacks.keys())
            combined_list = (
                modpack_names
                + sorted(custom_versions, reverse=True)
                + release_versions
                + snapshot_versions
            )
            self.version_combo['values'] = combined_list
            if release_versions:
                self.version_combo.set(release_versions[0])
            elif combined_list:
                self.version_combo.set(combined_list[0])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to populate version list: {e}")
            self.set_status(f"Error populating version list: {e}", "red")

    # --------------------------- JAVA DETECTION/BROWSING ---------------------------

    def find_java(self):
        """
        Basic attempt to find Java across different platforms.
        Tries some common locations on macOS, or simply uses `shutil.which("java")`.
        """
        # Try the system PATH first
        found = shutil.which("java")
        if found:
            return found

        # If on macOS, check some typical macOS Java locations
        if IS_MAC:
            java_locations = [
                "/usr/bin/java",
                "/Library/Java/JavaVirtualMachines",
                "/System/Library/Java/JavaVirtualMachines",
                os.path.expanduser("~/Library/Java/JavaVirtualMachines"),
                "/opt/homebrew/opt/java/bin/java",
                "/usr/local/opt/java/bin/java",
            ]
            for path in java_locations:
                if os.path.isfile(path):
                    return path
                elif os.path.isdir(path):
                    for root, _, files in os.walk(path):
                        if "bin" in root and "java" in files:
                            return os.path.join(root, "java")
        # Fallback
        return "java"

    def browse_java(self):
        filename = filedialog.askopenfilename(
            title="Select Java Executable",
            filetypes=[("Java Executable", "java"), ("All Files", "*.*")]
        )
        if filename:
            self.java_entry.delete(0, tk.END)
            self.java_entry.insert(0, filename)

    # --------------------------- ACCOUNTS UI ---------------------------

    def on_add_account(self):
        acc_type = self.acct_type_var.get()
        user = self.username_entry.get().strip()
        pwd = self.password_entry.get().strip()

        if not user:
            messagebox.showwarning("Input Error", "Username/Email cannot be empty!")
            return
        if acc_type == "tlauncher" and not pwd:
            result = messagebox.askyesno(
                "Password Missing",
                "You selected a TLauncher account but left the password empty. Continue anyway (treat as offline)?"
            )
            if not result:
                return

        try:
            add_account(acc_type, user, pwd)
            self.refresh_account_list()
            self.username_entry.delete(0, tk.END)
            self.password_entry.delete(0, tk.END)
            self.set_status(f"Account '{user}' added/updated.", "green")
        except Exception as e:
            messagebox.showerror("Account Error", f"Failed to add/update account: {e}")
            self.set_status(f"Error adding account: {e}", "red")

    def refresh_account_list(self):
        display_names = [f"{acc.get('type','N/A').capitalize()}: {acc.get('username','Unknown')}" for acc in accounts]
        self.account_combo['values'] = display_names
        if display_names:
            current_selection = self.account_var.get()
            if current_selection in display_names:
                self.account_combo.set(current_selection)
            else:
                self.account_combo.current(0)
        else:
            self.account_combo.set('')

    # --------------------------- LAUNCH BUTTON & THREADING ---------------------------

    def on_launch(self):
        selected_version_display = self.version_var.get()
        if not selected_version_display:
            messagebox.showerror("Error", "Please select a version or modpack.")
            return

        account_index = self.account_combo.current()
        if account_index == -1 and not accounts:
            result = messagebox.askyesno(
                "No Account Selected",
                "No accounts configured. Launch in Offline mode with username 'Player'?"
            )
            if result:
                selected_account = {
                    "type": "offline",
                    "username": "Player",
                    "uuid": str(uuidlib.uuid3(uuidlib.NAMESPACE_DNS, "Player")),
                    "token": "0"
                }
            else:
                return
        elif account_index == -1 and accounts:
            messagebox.showerror("Error", "Please select an account from the list.")
            return
        else:
            selected_account = accounts[account_index]

        try:
            ram_val = int(self.ram_spin.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid RAM value. Please enter a number (MB).")
            return

        java_path_val = self.java_entry.get().strip() or self.find_java()
        server_ip_val = self.server_entry.get().strip() or None
        port_val_str = self.port_entry.get().strip()
        port_val = None
        if port_val_str:
            try:
                port_val = int(port_val_str)
                if not (0 < port_val < 65536):
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Invalid Port number. Must be between 1 and 65535.")
                return

        # Check if user selected a known modpack from the list
        is_modpack = selected_version_display in getattr(self, "popular_modpacks", {})
        modpack_slug = self.popular_modpacks.get(selected_version_display) if is_modpack else None
        version_to_process = modpack_slug if is_modpack else selected_version_display

        use_rosetta = self.use_rosetta_var.get()
        lunar_client = self.lunar_client_var.get()
        ssl_verify = self.ssl_verify_var.get()

        self.launch_btn.config(state="disabled")
        self.set_status("Starting launch process...", "blue")

        launch_thread = threading.Thread(
            target=self._launch_task,
            args=(
                version_to_process,
                is_modpack,
                selected_account,
                ram_val,
                java_path_val,
                server_ip_val,
                port_val,
                use_rosetta,
                lunar_client,
                ssl_verify
            ),
            daemon=True
        )
        launch_thread.start()

    def _launch_task(
        self,
        item_to_launch,
        is_modpack,
        account,
        ram,
        java,
        server,
        port,
        use_rosetta,
        lunar_client,
        ssl_verify
    ):
        try:
            final_version_id = None
            game_directory = None

            if is_modpack:
                self.set_status(f"Installing modpack '{item_to_launch}'...", "blue")
                # You can place actual modpack installation logic here
                messagebox.showinfo("Modpack Support", "Modpack installation not fully implemented yet.")
                self.set_status("Ready", "black")
                self.root.after(0, self.launch_btn.config, {"state": "normal"})
                return
            else:
                final_version_id = item_to_launch
                self.set_status(f"Checking installation for version '{final_version_id}'...", "blue")
                install_version(final_version_id, status_callback=self.set_status, ssl_verify=ssl_verify)
                self.set_status(f"Version '{final_version_id}' ready. Preparing launch...", "blue")

            launch_game(
                version_id=final_version_id,
                account=account,
                ram_mb=ram,
                java_path=java,
                game_dir=game_directory,
                server_ip=server,
                port=port,
                status_callback=self.set_status,
                use_rosetta=use_rosetta,
                lunar_client=lunar_client,
                ssl_verify=ssl_verify
            )
            self.set_status(f"Launched {final_version_id} successfully!", "green")

        except Exception as e:
            error_message = f"Error during launch: {e}"
            print(f"ERROR: {error_message}")
            traceback.print_exc()
            self.set_status(f"Error: {e}", "red")
            self.root.after(0, messagebox.showerror, "Launch Failed", error_message)
        finally:
            self.root.after(0, self.launch_btn.config, {"state": "normal"})

    # --------------------------- STATUS HELPER ---------------------------

    def set_status(self, message, color="black"):
        self.root.after(0, self._update_status_ui, message, color)

    def _update_status_ui(self, message, color):
        self.status_var.set(message)
        # Attempt to set the label color in the bottom status bar
        for widget in self.root.winfo_children():
            if isinstance(widget, ttk.Frame) and widget.cget('relief') == tk.SUNKEN:
                for label in widget.winfo_children():
                    if isinstance(label, ttk.Label):
                        label.config(foreground=color)
                        break
                break

# ----------------------------------------------------------------------------------
#                                  MAIN ENTRY
# ----------------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = M1LauncherApp(root)
        root.mainloop()
    except Exception as e:
        print(f"Fatal error: {e}")
        traceback.print_exc()
        if 'root' in locals() and root:
            messagebox.showerror("Fatal Error", f"A fatal error occurred: {e}")
