import traceback
import os, sys, json, shutil, zipfile, threading
import urllib.request
import urllib.error
import ssl
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re
import subprocess
import uuid as uuidlib
import platform

# --- Constants ---
USER_AGENT = "Mozilla/5.0 (Macintosh; Apple Silicon Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36"
LUNAR_API_BASE = "https://api.lunarclientprod.com"
LUNAR_COSMETICS_ENDPOINT = f"{LUNAR_API_BASE}/launcher/cosmetics/users"
TLAUNCHER_SKIN_API = "https://auth.tlauncher.org/skin/"

# --- SSL Context Setup ---
def get_ssl_context(verify=False):
    if verify:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl._create_unverified_context()
    return ctx

# --- Directory Setup ---
mc_dir = os.path.expanduser("~/Library/Application Support/minecraft")
if not os.path.isdir(mc_dir):
    os.makedirs(mc_dir, exist_ok=True)

VERSIONS_DIR = os.path.join(mc_dir, "versions")
ASSETS_DIR = os.path.join(mc_dir, "assets")
MODPACKS_DIR = os.path.join(mc_dir, "modpacks")
LIBRARIES_DIR = os.path.join(mc_dir, "libraries")
LUNAR_CACHE_DIR = os.path.join(mc_dir, "lunar_cache")
TLAUNCHER_SKINS_DIR = os.path.join(mc_dir, "tlauncher_skins")

for d in [VERSIONS_DIR, MODPACKS_DIR, os.path.join(ASSETS_DIR, "indexes"), os.path.join(ASSETS_DIR, "objects"), LIBRARIES_DIR, LUNAR_CACHE_DIR, TLAUNCHER_SKINS_DIR]:
    os.makedirs(d, exist_ok=True)

# URLs
VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
ASSET_BASE_URL = "https://resources.download.minecraft.net/"
LIBRARIES_BASE_URL = "https://libraries.minecraft.net/"
FORGE_MAVEN_URL = "https://maven.minecraftforge.net/"

# --- Account Management ---
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
    if not email_username: return
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

# --- Cosmetics Functions (Lunar + TLauncher) ---
def fetch_lunar_cosmetics(uuid, ssl_verify=False):
    cache_file = os.path.join(LUNAR_CACHE_DIR, f"{uuid}_cosmetics.json")
    if os.path.isfile(cache_file):
        with open(cache_file, 'r') as f:
            return json.load(f)
    
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    params = {"uuids": uuid}
    url = f"{LUNAR_COSMETICS_ENDPOINT}?{urllib.parse.urlencode(params)}"
    try:
        context = get_ssl_context(ssl_verify)
        req = urllib.request.Request(url, headers=headers)
        print(f"Fetching Lunar cosmetics from: {url}")
        with urllib.request.urlopen(req, context=context) as response:
            print(f"Response headers: {response.getheaders()}")
            data = json.loads(response.read().decode())
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=4)
            return data
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code} fetching Lunar cosmetics from {url}: {e.reason}")
        print(f"Response headers: {e.headers}")
        return {}
    except Exception as e:
        print(f"Failed to fetch Lunar cosmetics for UUID {uuid} from {url}: {e}")
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
        download_file(cape_url, cape_file, "TLauncher cape", ssl_verify)
        return skin_file, cape_file
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code} fetching TLauncher skin/cape for {username}: {e.reason}")
        return None, None
    except Exception as e:
        print(f"Failed to fetch TLauncher skin/cape for {username}: {e}")
        return None, None

def download_file(url, dest_path, description="file", ssl_verify=False):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    ssl_context = get_ssl_context(ssl_verify)
    try:
        print(f"Downloading {description}: {os.path.basename(dest_path)} from {url}")
        with urllib.request.urlopen(req, context=ssl_context) as response:
            print(f"Response headers: {response.getheaders()}")
            shutil.copyfileobj(response, open(dest_path, 'wb'))
        print(f"Finished downloading {os.path.basename(dest_path)}")
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code} downloading {description} from {url}: {e.reason}")
        print(f"Response headers: {e.headers}")
        raise Exception(f"Failed to download {description} from {url}: HTTP Error {e.code} - {e.reason}")
    except Exception as e:
        print(f"Failed to download {description} from {url}: {e}")
        raise Exception(f"Failed to download {description} from {url}: {e}")

# --- Version Manifest Loading ---
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

# --- M1 Mac Specific Functions ---
def is_arm64():
    return platform.machine() == 'arm64'

def detect_rosetta():
    try:
        result = subprocess.run(['sysctl', '-n', 'sysctl.proc_translated'], capture_output=True, text=True)
        return result.stdout.strip() == '1'
    except:
        return False

def run_with_rosetta(cmd):
    if is_arm64() and not detect_rosetta():
        return ['arch', '-x86_64'] + cmd
    return cmd

# --- Minecraft Installation Logic ---
def install_version(version_id, status_callback=None, ssl_verify=False):
    if status_callback: status_callback(f"Checking version: {version_id}...", "#00ccff")
    version_folder = os.path.join(VERSIONS_DIR, version_id)
    version_json_path = os.path.join(version_folder, f"{version_id}.json")
    version_jar_path = os.path.join(version_folder, f"{version_id}.jar")

    if not os.path.isfile(version_json_path):
        if version_id not in all_versions:
            raise Exception(f"Version '{version_id}' not found in Mojang manifest.")
        version_url = all_versions[version_id]
        os.makedirs(version_folder, exist_ok=True)
        if status_callback: status_callback(f"Downloading version JSON for {version_id}...", "#00ccff")
        download_file(version_url, version_json_path, f"version JSON ({version_id})", ssl_verify)

    with open(version_json_path, 'r') as f:
        version_data = json.load(f)

    parent_id = version_data.get("inheritsFrom")
    parent_data = {}
    if parent_id:
        if status_callback: status_callback(f"Version {version_id} inherits from {parent_id}. Installing parent...", "#00ccff")
        install_version(parent_id, status_callback, ssl_verify)
        parent_json_path = os.path.join(VERSIONS_DIR, parent_id, f"{parent_id}.json")
        with open(parent_json_path, 'r') as pf:
            parent_data = json.load(pf)

    client_info = version_data.get("downloads", {}).get("client")
    if client_info and not os.path.isfile(version_jar_path):
        client_url = client_info.get("url")
        if client_url:
            if status_callback: status_callback(f"Downloading client JAR for {version_id}...", "#00ccff")
            download_file(client_url, version_jar_path, f"client JAR ({version_id})", ssl_verify)

    libraries = version_data.get("libraries", []) + parent_data.get("libraries", [])
    total_libs = len(libraries)
    for i, lib in enumerate(libraries):
        rules = lib.get("rules", [])
        allowed = not rules or any(rule["action"] == "allow" and (not rule.get("os") or rule["os"].get("name") == "osx") for rule in rules)
        if not allowed: continue

        artifact = lib.get("downloads", {}).get("artifact")
        if artifact and artifact.get("path"):
            lib_path = os.path.join(LIBRARIES_DIR, artifact["path"])
            if not os.path.isfile(lib_path):
                lib_url = artifact.get("url") or LIBRARIES_BASE_URL + artifact["path"]
                if status_callback: status_callback(f"Downloading library {i+1}/{total_libs}: {os.path.basename(lib_path)}", "#00ccff")
                download_file(lib_url, lib_path, f"library ({os.path.basename(lib_path)})", ssl_verify)

        natives_info = lib.get("natives")
        classifiers = lib.get("downloads", {}).get("classifiers", {})
        if natives_info and classifiers:
            native_key = 'natives-osx-arm64' if is_arm64() and 'natives-osx-arm64' in classifiers else natives_info.get('osx', '').replace("${arch}", "64")
            if native_key in classifiers:
                native_artifact = classifiers[native_key]
                native_path = os.path.join(LIBRARIES_DIR, native_artifact["path"])
                if not os.path.isfile(native_path):
                    native_url = native_artifact.get("url") or LIBRARIES_BASE_URL + native_artifact["path"]
                    if status_callback: status_callback(f"Downloading native library {i+1}/{total_libs}: {os.path.basename(native_path)}", "#00ccff")
                    download_file(native_url, native_path, f"native library ({os.path.basename(native_path)})", ssl_verify)
                natives_dir = os.path.join(version_folder, "natives")
                os.makedirs(natives_dir, exist_ok=True)
                with zipfile.ZipFile(native_path, 'r') as zf:
                    for member in zf.namelist():
                        if not member.startswith("META-INF/") and not member.endswith('/'):
                            zf.extract(member, natives_dir)

    asset_index_info = version_data.get("assetIndex") or parent_data.get("assetIndex")
    if asset_index_info:
        idx_id = asset_index_info["id"]
        idx_url = asset_index_info["url"]
        idx_dest = os.path.join(ASSETS_DIR, "indexes", f"{idx_id}.json")
        if not os.path.isfile(idx_dest):
            if status_callback: status_callback(f"Downloading asset index {idx_id}...", "#00ccff")
            download_file(idx_url, idx_dest, f"asset index ({idx_id})", ssl_verify)

        with open(idx_dest, 'r') as f:
            idx_data = json.load(f)
        total_assets = len(idx_data["objects"])
        assets_downloaded = 0
        for asset_name, info in idx_data["objects"].items():
            hash_val = info.get("hash")
            if hash_val:
                subdir = hash_val[:2]
                asset_path = os.path.join(ASSETS_DIR, "objects", subdir, hash_val)
                if not os.path.isfile(asset_path):
                    assets_downloaded += 1
                    if status_callback: status_callback(f"Downloading asset {assets_downloaded}/{total_assets}: {asset_name}", "#00ccff")
                    download_file(ASSET_BASE_URL + f"{subdir}/{hash_val}", asset_path, f"asset ({hash_val[:8]})", ssl_verify)

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

    if status_callback: status_callback(f"Version {version_id} installation complete.", "#00ff00")

# --- Lunar Client Setup ---
def setup_lunar_client(version_id, account, status_callback=None, ssl_verify=False):
    if account["type"] == "offline":
        if status_callback: status_callback("Skipping Lunar setup for offline mode.", "#00ccff")
        return  # Skip HTTP calls for offline mode
    
    if status_callback: status_callback(f"Setting up Lunar Client for {version_id}...", "#00ccff")
    lunar_dir = os.path.expanduser("~/.lunarclient")
    for d in [os.path.join(lunar_dir, "offline"), os.path.join(lunar_dir, "jre"), os.path.join(lunar_dir, "cosmetics")]:
        os.makedirs(d, exist_ok=True)

    offline_marker = os.path.join(lunar_dir, "offline", ".offline")
    if not os.path.exists(offline_marker):
        with open(offline_marker, 'w') as f:
            f.write("1")

    lunar_versions_dir = os.path.join(lunar_dir, "game-versions")
    if not os.path.exists(lunar_versions_dir):
        os.symlink(VERSIONS_DIR, lunar_versions_dir, target_is_directory=True)

    settings_path = os.path.join(lunar_dir, "settings.json")
    if not os.path.exists(settings_path):
        with open(settings_path, 'w') as f:
            json.dump({"gameDir": mc_dir, "jreDir": os.path.join(lunar_dir, "jre"), "lastVersion": version_id, "offline": True}, f, indent=4)

    cosmetics_data = fetch_lunar_cosmetics(account["uuid"], ssl_verify)
    if cosmetics_data.get("users"):
        user_cosmetics = cosmetics_data["users"].get(account["uuid"], {})
        cape = user_cosmetics.get("cape")
        if cape and cape.get("textureUrl"):
            cape_path = os.path.join(lunar_dir, "cosmetics", f"cape_{account['uuid']}.png")
            download_file(cape["textureUrl"], cape_path, "Lunar cape texture", ssl_verify)
            cape_asset_path = os.path.join(ASSETS_DIR, "objects", cape["hash"][:2], cape["hash"])
            os.makedirs(os.path.dirname(cape_asset_path), exist_ok=True)
            shutil.copy(cape_path, cape_asset_path)

    if status_callback: status_callback(f"Lunar Client setup complete for {version_id}", "#00ff00")

# --- TLauncher Cosmetics Setup ---
def setup_tlauncher_cosmetics(account, status_callback=None, ssl_verify=False):
    if account["type"] == "offline":
        if status_callback: status_callback("Skipping TLauncher cosmetics for offline mode.", "#00ccff")
        return  # Skip HTTP calls for offline mode
    
    if status_callback: status_callback(f"Setting up TLauncher cosmetics for {account['username']}...", "#00ccff")
    skin_path, cape_path = fetch_tlauncher_skin(account["username"], ssl_verify)
    if skin_path:
        skin_asset_path = os.path.join(ASSETS_DIR, "objects", "skin", f"{account['uuid']}.png")
        os.makedirs(os.path.dirname(skin_asset_path), exist_ok=True)
        shutil.copy(skin_path, skin_asset_path)
    if cape_path:
        cape_asset_path = os.path.join(ASSETS_DIR, "objects", "cape", f"{account['uuid']}.png")
        os.makedirs(os.path.dirname(cape_asset_path), exist_ok=True)
        shutil.copy(cape_path, cape_asset_path)
    if status_callback: status_callback(f"TLauncher cosmetics setup complete for {account['username']}", "#00ff00")

# --- Game Launch Logic ---
def launch_game(version_id, account, ram_mb=1024, java_path="java", game_dir=None, server_ip=None, port=None, 
               status_callback=None, use_rosetta=False, lunar_client=False, ssl_verify=False):
    if status_callback: status_callback(f"Preparing to launch {version_id}...", "#00ccff")
    effective_game_dir = game_dir or mc_dir
    
    if lunar_client and account["type"] != "offline":
        setup_lunar_client(version_id, account, status_callback, ssl_verify)
    if account["type"] == "tlauncher":
        setup_tlauncher_cosmetics(account, status_callback, ssl_verify)
    
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

    for lib in vdata.get("libraries", []) + parent_data.get("libraries", []):
        if any(rule["action"] == "allow" and (not rule.get("os") or rule["os"].get("name") == "osx") for rule in lib.get("rules", [])) or not lib.get("rules"):
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

    jvm_args = [f"-Xmx{ram_mb}M", f"-Djava.library.path={natives_dir_absolute}"]
    if is_arm64():
        jvm_args.extend(["-XX:+UseG1GC", "-XX:MaxGCPauseMillis=200", "-XX:ParallelGCThreads=4", "-Dapple.awt.application.name=Cat Client"])
    if lunar_client and account["type"] != "offline":
        jvm_args.extend(["-Dfml.ignoreInvalidMinecraftCertificates=true", "-Dorg.lwjgl.opengl.Display.allowSoftwareOpenGL=true"])
        main_class = "com.moonsworth.lunar.genesis.Genesis" if "net.minecraft.client.main.Main" in main_class else main_class

    args_data = vdata.get("arguments", {})
    parent_args_data = parent_data.get("arguments", {})
    raw_jvm_args = parent_args_data.get("jvm", []) + args_data.get("jvm", [])
    raw_game_args = parent_args_data.get("game", []) + args_data.get("game", []) or vdata.get("minecraftArguments", "").split()

    replacements = {
        "${auth_player_name}": account["username"],
        "${version_name}": version_id,
        "${game_directory}": effective_game_dir,
        "${assets_root}": os.path.abspath(ASSETS_DIR),
        "${assets_index_name}": (vdata.get("assetIndex") or parent_data.get("assetIndex", {})).get("id", "legacy"),
        "${auth_uuid}": account["uuid"],
        "${auth_access_token}": account["token"] if account["type"] != "offline" else "0",
        "${user_type}": "msa" if account["type"] == "microsoft" else "legacy",
        "${version_type}": vdata.get("type", "release"),
        "${natives_directory}": natives_dir_absolute,
        "${classpath_separator}": os.pathsep,
        "${launcher_name}": "LunarClient" if lunar_client and account["type"] != "offline" else "CatClient",
        "${launcher_version}": "0.1.0"
    }

    for arg in raw_jvm_args:
        if isinstance(arg, str):
            jvm_args.append(arg.format(**replacements))
        elif isinstance(arg, dict) and any(rule["action"] == "allow" and (not rule.get("os") or rule["os"].get("name") == "osx") for rule in arg["rules"]):
            value = arg["value"]
            jvm_args.extend([v.format(**replacements)] if isinstance(value, list) else [v.format(**replacements)])

    jvm_args.extend(["-cp", os.pathsep.join(classpath)])
    game_args = [arg.format(**replacements) if isinstance(arg, str) else arg["value"][0].format(**replacements) for arg in raw_game_args if isinstance(arg, str) or (isinstance(arg, dict) and "value" in arg)]

    command = [java_path] + jvm_args + [main_class] + game_args
    if use_rosetta:
        command = run_with_rosetta(command)

    if status_callback: status_callback(f"Launching Minecraft {version_id}...", "#00ccff")
    subprocess.Popen(command, cwd=effective_game_dir)

# --- GUI (Lunar Client Style) ---
class M1LauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Cat Client")
        self.root.geometry("800x450")  # Lunar's compact size
        self.root.configure(bg="#1C2526")  # Lunar's dark grey

        self.version_manifest = {"versions": []}
        self.is_launching = False
        self.lunar_client_var = tk.BooleanVar(value=True)  # Default to Lunar mode

        # Main frame (centered content)
        main_frame = tk.Frame(root, bg="#1C2526")
        main_frame.pack(expand=True)

        # Top bar (account info)
        top_frame = tk.Frame(main_frame, bg="#1C2526")
        top_frame.pack(side="top", fill="x", pady=(10, 0))
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(top_frame, textvariable=self.account_var, state="readonly", style="Lunar.TCombobox", width=20)
        self.account_combo.pack(side="right", padx=10)
        tk.Button(top_frame, text="Remove Account", command=self.remove_account, bg="#00CCFF", fg="black", font=("Arial", 10), relief="flat").pack(side="right", padx=5)
        tk.Button(top_frame, text="Add Account", command=self.show_account_window, bg="#00CCFF", fg="black", font=("Arial", 10), relief="flat").pack(side="right", padx=5)

        # Central content (version + play button)
        center_frame = tk.Frame(main_frame, bg="#1C2526")
        center_frame.pack(expand=True)
        
        self.version_var = tk.StringVar()
        self.version_combo = ttk.Combobox(center_frame, textvariable=self.version_var, state="readonly", style="Lunar.TCombobox", width=15)
        self.version_combo.pack(pady=10)
        
        self.launch_btn = tk.Button(center_frame, text=">", command=self.on_launch, bg="#00CCFF", fg="black", font=("Arial", 24, "bold"), relief="flat", width=10, height=2)
        self.launch_btn.pack(pady=20)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_frame = tk.Frame(root, bg="#1C2526")
        status_frame.pack(side="bottom", fill="x", pady=5)
        self.status_label = tk.Label(status_frame, textvariable=self.status_var, bg="#1C2526", fg="#00CCFF", font=("Arial", 10))
        self.status_label.pack(side="left", padx=10)

        # Style
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Lunar.TCombobox", fieldbackground="#2A3435", background="#2A3435", foreground="#FFFFFF", arrowcolor="#00CCFF", borderwidth=0)
        style.map("Lunar.TCombobox", fieldbackground=[("readonly", "#2A3435")], background=[("readonly", "#2A3435")])

        self.refresh_account_list()
        self.load_manifest()

    def show_account_window(self):
        account_window = tk.Toplevel(self.root)
        account_window.title("Add Account")
        account_window.geometry("300x200")
        account_window.configure(bg="#1C2526")
        account_window.transient(self.root)
        account_window.grab_set()

        tk.Label(account_window, text="Account Type:", bg="#1C2526", fg="#FFFFFF").pack(pady=5)
        acct_type_var = tk.StringVar(value="lunar")
        for text, val in [("Lunar", "lunar"), ("TLauncher", "tlauncher"), ("Offline", "offline")]:
            tk.Radiobutton(account_window, text=text, variable=acct_type_var, value=val, bg="#1C2526", fg="#00CCFF", selectcolor="#2A3435").pack()

        tk.Label(account_window, text="Username:", bg="#1C2526", fg="#FFFFFF").pack(pady=5)
        username_entry = tk.Entry(account_window, bg="#2A3435", fg="#FFFFFF", insertbackground="#00CCFF")
        username_entry.pack()

        tk.Label(account_window, text="Password:", bg="#1C2526", fg="#FFFFFF").pack(pady=5)
        password_entry = tk.Entry(account_window, show="*", bg="#2A3435", fg="#FFFFFF", insertbackground="#00CCFF")
        password_entry.pack()

        def add():
            acc_type = acct_type_var.get()
            user = username_entry.get().strip()
            pwd = password_entry.get().strip()
            if not user:
                messagebox.showwarning("Input Error", "Username cannot be empty!", parent=account_window)
                return
            if acc_type == "tlauncher" and not pwd:
                result = messagebox.askyesno("Password Missing", "TLauncher account without password. Continue as offline?", parent=account_window)
                if not result: return
            try:
                add_account(acc_type, user, pwd)
                self.refresh_account_list()
                account_window.destroy()
                self.set_status(f"Account '{user}' added!", "#00FF00")
            except Exception as e:
                messagebox.showerror("Account Error", f"Failed to add account: {e}", parent=account_window)
                self.set_status(f"Error: {e}", "#FF0000")

        tk.Button(account_window, text="Add", command=add, bg="#00CCFF", fg="black", font=("Arial", 10), relief="flat").pack(pady=10)

    def remove_account(self):
        if not accounts:
            messagebox.showinfo("No Accounts", "No accounts to remove!")
            return
        account_index = self.account_combo.current()
        if account_index == -1:
            messagebox.showwarning("No Selection", "Please select an account to remove!")
            return
        selected_account = accounts[account_index]
        result = messagebox.askyesno("Confirm Removal", f"Are you sure you want to remove '{selected_account['username']}'?")
        if result:
            try:
                accounts.pop(account_index)
                save_accounts()
                self.refresh_account_list()
                self.set_status(f"Account '{selected_account['username']}' removed!", "#00FF00")
            except Exception as e:
                messagebox.showerror("Removal Error", f"Failed to remove account: {e}")
                self.set_status(f"Error: {e}", "#FF0000")

    def load_manifest(self):
        self.set_status("Loading manifest...", "#00CCFF")
        try:
            self.version_manifest = load_version_manifest(ssl_verify=False)
            self.populate_version_list()
            self.set_status("Ready", "#00CCFF")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load version manifest: {e}")
            self.set_status(f"Error: {e}", "#FF0000")

    def populate_version_list(self):
        try:
            releases = sorted([v['id'] for v in self.version_manifest['versions'] if v['type'] == 'release'], reverse=True)
            self.version_combo['values'] = releases
            if releases:
                self.version_combo.set(releases[0])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to populate version list: {e}")
            self.set_status(f"Error: {e}", "#FF0000")

    def set_status(self, message, color="#00CCFF"):
        self.status_var.set(message)
        self.status_label.config(fg=color)

    def refresh_account_list(self):
        self.account_combo['values'] = [f"{acc['username']}" for acc in accounts]
        if accounts:
            self.account_combo.current(0)
        else:
            self.account_var.set("No Accounts")

    def on_launch(self):
        if self.is_launching:
            self.set_status("Launch in progress, please wait...", "#FFCC00")
            return

        if not self.version_var.get():
            messagebox.showerror("Error", "Select a version!")
            return
        account_index = self.account_combo.current()
        if account_index == -1 and not accounts:
            result = messagebox.askyesno("No Account", "Launch offline with 'Player'?")
            if result:
                selected_account = {"type": "offline", "username": "Player", "uuid": str(uuidlib.uuid3(uuidlib.NAMESPACE_DNS, "Player")), "token": "0"}
            else:
                return
        elif account_index == -1 and accounts:
            messagebox.showerror("Error", "Select an account!")
            return
        else:
            selected_account = accounts[account_index]

        self.is_launching = True
        self.launch_btn.config(state="disabled", text=">")
        self.root.update_idletasks()
        threading.Thread(
            target=self._launch_task,
            args=(self.version_var.get(), False, selected_account, 4096, "java", None, None, False, self.lunar_client_var.get(), False),
            daemon=True
        ).start()

    def _launch_task(self, item_to_launch, is_modpack, account, ram, java, server, port, use_rosetta, lunar_client, ssl_verify):
        try:
            self.set_status(f"Checking {item_to_launch}...", "#00CCFF")
            install_version(item_to_launch, self.set_status, ssl_verify)
            self.set_status(f"{item_to_launch} ready. Launching...", "#00CCFF")
            launch_game(
                version_id=item_to_launch,
                account=account,
                ram_mb=ram,
                java_path=java,
                status_callback=self.set_status,
                lunar_client=lunar_client,
                ssl_verify=ssl_verify
            )
            self.set_status(f"Launched {item_to_launch}!", "#00FF00")
        except Exception as e:
            self.set_status(f"Error: {e}", "#FF0000")
            messagebox.showerror("Launch Failed", f"Error: {e}")
        finally:
            self.is_launching = False
            self.launch_btn.config(state="normal", text=">")
            self.root.update_idletasks()

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