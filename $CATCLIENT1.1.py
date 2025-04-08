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
import time

# --- Constants ---
USER_AGENT = "Mozilla/5.0 (Macintosh; Apple Silicon Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36"
VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
ASSET_BASE_URL = "https://resources.download.minecraft.net/"
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
lunar_dir = os.path.expanduser("~/.lunarclient")
for d in [mc_dir, lunar_dir]:
    if not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except PermissionError as e:
            print(f"Permission denied creating {d}: {e}")
            sys.exit(1)

VERSIONS_DIR = os.path.join(mc_dir, "versions")
ASSETS_DIR = os.path.join(mc_dir, "assets")
LIBRARIES_DIR = os.path.join(mc_dir, "libraries")
LUNAR_CACHE_DIR = os.path.join(mc_dir, "lunar_cache")

for d in [VERSIONS_DIR, os.path.join(ASSETS_DIR, "indexes"), os.path.join(ASSETS_DIR, "objects"), LIBRARIES_DIR, LUNAR_CACHE_DIR]:
    try:
        os.makedirs(d, exist_ok=True)
    except PermissionError as e:
        print(f"Permission denied creating {d}: {e}")
        sys.exit(1)

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
    except PermissionError as e:
        print(f"Permission denied saving accounts: {e}")
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

# --- Download Function with Retries ---
def download_file(url, dest_path, description="file", ssl_verify=False, retries=3):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    ssl_context = get_ssl_context(ssl_verify)
    attempt = 0
    while attempt < retries:
        try:
            print(f"Attempt {attempt + 1}/{retries} - Downloading {description}: {os.path.basename(dest_path)} from {url}")
            with urllib.request.urlopen(req, context=ssl_context) as response:
                shutil.copyfileobj(response, open(dest_path, 'wb'))
            print(f"Finished downloading {os.path.basename(dest_path)}")
            return True
        except urllib.error.HTTPError as e:
            print(f"HTTP Error {e.code} downloading {description} from {url}: {e.reason}")
            attempt += 1
            time.sleep(2 ** attempt)
        except PermissionError as e:
            print(f"Permission denied writing {dest_path}: {e}")
            raise
        except Exception as e:
            print(f"Failed to download {description} from {url}: {e}")
            attempt += 1
            time.sleep(2 ** attempt)
    raise Exception(f"Failed to download {description} after {retries} attempts")

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

def run_with_rosetta(cmd):
    if is_arm64():
        return ['arch', '-x86_64'] + cmd
    return cmd

# --- Install Version ---
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

    client_info = version_data.get("downloads", {}).get("client")
    if client_info and not os.path.isfile(version_jar_path):
        client_url = client_info.get("url")
        if client_url:
            if status_callback: status_callback(f"Downloading client JAR for {version_id}...", "#00ccff")
            download_file(client_url, version_jar_path, f"client JAR ({version_id})", ssl_verify)
        else:
            raise Exception(f"No client URL found for {version_id}")

    if status_callback: status_callback(f"Version {version_id} ready.", "#00ff00")

# --- Lunar Client Launch Logic ---
def launch_lunar_client(version_id, account, ram_mb=4096, java_path="java", status_callback=None, ssl_verify=False):
    if status_callback: status_callback(f"Preparing Lunar Client {version_id}...", "#00ccff")

    if not account.get("username"):
        error_msg = "No username provided!"
        print(error_msg)
        if status_callback: status_callback(error_msg, "#ff0000")
        raise ValueError(error_msg)

    # Check and setup Lunar dir
    for d in [os.path.join(lunar_dir, "offline"), os.path.join(lunar_dir, "jre"), os.path.join(lunar_dir, "cosmetics")]:
        os.makedirs(d, exist_ok=True)
    
    lunar_versions_dir = os.path.join(lunar_dir, "game-versions")
    if not os.path.exists(lunar_versions_dir):
        try:
            os.symlink(VERSIONS_DIR, lunar_versions_dir, target_is_directory=True)
        except OSError:
            shutil.copytree(VERSIONS_DIR, lunar_versions_dir, dirs_exist_ok=True)

    settings_path = os.path.join(lunar_dir, "settings.json")
    if not os.path.exists(settings_path):
        with open(settings_path, 'w') as f:
            json.dump({"gameDir": mc_dir, "jreDir": os.path.join(lunar_dir, "jre"), "lastVersion": version_id, "offline": account["type"] == "offline"}, f, indent=4)

    # Install base version
    install_version(version_id, status_callback, ssl_verify)

    # Check for Lunar JAR, fallback to vanilla if missing
    lunar_jar = os.path.join(lunar_dir, "lunar-prod.jar")  # Adjust this if Lunar JAR name differs
    if not os.path.isfile(lunar_jar):
        print(f"Lunar Client JAR not found at {lunar_jar}! Falling back to vanilla JAR...")
        if status_callback: status_callback("Lunar JAR missing, using vanilla JAR...", "#ffcc00")
        lunar_jar = os.path.join(VERSIONS_DIR, version_id, f"{version_id}.jar")
        main_class = "net.minecraft.client.main.Main"  # Vanilla main class
        if not os.path.isfile(lunar_jar):
            error_msg = f"Vanilla JAR not found either! Expected {lunar_jar}"
            print(error_msg)
            if status_callback: status_callback(error_msg, "#ff0000")
            raise FileNotFoundError(error_msg)
    else:
        main_class = "com.moonsworth.lunar.genesis.Genesis"  # Lunar main class

    classpath = [lunar_jar]
    natives_dir = os.path.join(lunar_dir, "natives")

    jvm_args = [
        f"-Xmx{ram_mb}M",
        f"-Djava.library.path={natives_dir}",
        "-Dlunar.offline={}".format("true" if account["type"] == "offline" else "false"),
        "-Dfml.ignoreInvalidMinecraftCertificates=true"
    ]
    if is_arm64():
        jvm_args.extend(["-XX:+UseG1GC", "-XX:MaxGCPauseMillis=200", "-XX:ParallelGCThreads=4"])

    game_args = [
        "--username", account["username"],
        "--uuid", account["uuid"],
        "--accessToken", account["token"] if account["type"] != "offline" else "0",
        "--version", version_id,
        "--gameDir", mc_dir,
        "--assetDir", ASSETS_DIR
    ]

    command = [java_path] + jvm_args + ["-cp", os.pathsep.join(classpath)] + [main_class] + game_args
    command = run_with_rosetta(command)

    print(f"Launch command: {' '.join(command)}")
    if status_callback: status_callback(f"Launching Lunar Client {version_id}...", "#00ccff")
    try:
        process = subprocess.Popen(command, cwd=mc_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate(timeout=10)
        if process.returncode and process.returncode != 0:
            error_msg = f"Launch failed: {stderr.decode() if stderr else 'Unknown error'}"
            print(error_msg)
            if status_callback: status_callback(error_msg, "#ff0000")
            raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
    except Exception as e:
        print(f"Launch error: {e}")
        if status_callback: status_callback(f"Error: {e}", "#ff0000")
        raise

# --- Lunar-Style GUI ---
class LunarLauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Lunar Client")
        self.root.geometry("900x500")
        self.root.configure(bg="#1C2526")
        self.root.resizable(False, False)

        self.version_manifest = {"versions": []}
        self.is_launching = False

        main_frame = tk.Frame(root, bg="#1C2526")
        main_frame.pack(expand=True, fill="both")

        tk.Label(main_frame, text="Lunar Client", font=("Arial", 36, "bold"), fg="#00CCFF", bg="#1C2526").pack(pady=(20, 10))

        selector_frame = tk.Frame(main_frame, bg="#1C2526")
        selector_frame.pack(pady=20)

        tk.Label(selector_frame, text="Version", font=("Arial", 12), fg="#FFFFFF", bg="#1C2526").grid(row=0, column=0, padx=10)
        self.version_var = tk.StringVar()
        self.version_combo = ttk.Combobox(selector_frame, textvariable=self.version_var, state="readonly", style="Lunar.TCombobox", width=15)
        self.version_combo.grid(row=1, column=0, padx=10)

        tk.Label(selector_frame, text="Account", font=("Arial", 12), fg="#FFFFFF", bg="#1C2526").grid(row=0, column=1, padx=10)
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(selector_frame, textvariable=self.account_var, state="readonly", style="Lunar.TCombobox", width=20)
        self.account_combo.grid(row=1, column=1, padx=10)

        self.launch_btn = tk.Button(main_frame, text="LAUNCH", command=self.on_launch, bg="#00CCFF", fg="#FFFFFF", font=("Arial", 18, "bold"), relief="flat", width=15, height=2)
        self.launch_btn.pack(pady=30)

        self.status_var = tk.StringVar(value="Ready")
        status_frame = tk.Frame(root, bg="#1C2526")
        status_frame.pack(side="bottom", fill="x", pady=10)
        self.status_label = tk.Label(status_frame, textvariable=self.status_var, bg="#1C2526", fg="#00CCFF", font=("Arial", 10))
        self.status_label.pack(side="left", padx=20)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Lunar.TCombobox", fieldbackground="#2A3435", background="#2A3435", foreground="#FFFFFF", arrowcolor="#00CCFF", borderwidth=0)
        style.map("Lunar.TCombobox", fieldbackground=[("readonly", "#2A3435")], background=[("readonly", "#2A3435")])

        self.refresh_account_list()
        self.load_manifest()

    def load_manifest(self):
        self.set_status("Loading versions...", "#00CCFF")
        try:
            self.version_manifest = load_version_manifest(ssl_verify=False)
            releases = sorted([v['id'] for v in self.version_manifest['versions'] if v['type'] == 'release'], reverse=True)
            self.version_combo['values'] = releases
            if releases:
                self.version_combo.set(releases[0])
            self.set_status("Ready", "#00CCFF")
        except Exception as e:
            self.set_status(f"Error: {e}", "#FF0000")
            messagebox.showerror("Error", f"Failed to load versions: {e}")

    def refresh_account_list(self):
        self.account_combo['values'] = [f"{acc['username']}" for acc in accounts]
        if accounts:
            self.account_combo.current(0)
        else:
            self.add_default_account()

    def add_default_account(self):
        add_account("offline", "Player")
        self.refresh_account_list()

    def set_status(self, message, color="#00CCFF"):
        self.status_var.set(message)
        self.status_label.config(fg=color)

    def on_launch(self):
        if self.is_launching:
            self.set_status("Launch in progress...", "#FFCC00")
            return

        version = self.version_var.get()
        if not version:
            messagebox.showerror("Error", "Select a version!")
            return

        account_index = self.account_combo.current()
        if account_index == -1:
            messagebox.showerror("Error", "Select an account!")
            return

        selected_account = accounts[account_index]

        self.is_launching = True
        self.launch_btn.config(state="disabled", text="LAUNCHING")
        self.root.update_idletasks()
        threading.Thread(
            target=self._launch_task,
            args=(version, selected_account),
            daemon=True
        ).start()

    def _launch_task(self, version_id, account):
        try:
            launch_lunar_client(version_id, account, status_callback=self.set_status)
            self.set_status(f"Launched {version_id}!", "#00FF00")
        except Exception as e:
            self.set_status(f"Error: {e}", "#FF0000")
            messagebox.showerror("Launch Failed", f"Error: {e}")
        finally:
            self.is_launching = False
            self.launch_btn.config(state="normal", text="LAUNCH")
            self.root.update_idletasks()

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = LunarLauncherApp(root)
        root.mainloop()
    except Exception as e:
        print(f"Fatal error: {e}")
        traceback.print_exc()
        if 'root' in locals() and root:
            messagebox.showerror("Fatal Error", f"A fatal error occurred: {e}")