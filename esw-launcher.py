#!/usr/bin/env python3
import os, sys, subprocess, urllib.request, hashlib

venv_path = os.path.expanduser("~/.venv/exegol-replay")
python_path = os.path.join(venv_path, "bin", "python3")
base_dir = os.path.dirname(os.path.abspath(__file__))
script_real = os.path.join(base_dir, "exegolsessionsviewer.py")
tty2img_path = os.path.join(base_dir, "tty2img.py")

# GitHub RAW URLs
tty2img_url = "https://raw.githubusercontent.com/Frozenka/Exegol-Session-Viewer/main/tty2img.py"
exegolviewer_url = "https://raw.githubusercontent.com/Frozenka/Exegol-Session-Viewer/main/exegolsessionsviewer.py"

def sha256sum(filename):
    h = hashlib.sha256()
    try:
        with open(filename, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                h.update(chunk)
        return h.hexdigest()
    except FileNotFoundError:
        return None

def get_remote_sha256(url):
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(url) as r:
            while True:
                chunk = r.read(4096)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        print(f"[!] Error fetching remote file: {e}")
        return None

def ask_update(file_name):
    while True:
        rep = input(f"[!] An update for {file_name} is available. Do you want to apply it? (Y/n) ").strip().lower()
        if rep in ["", "y", "yes"]:
            return True
        elif rep in ["n", "no"]:
            return False

def auto_update(local_path, remote_url, main_script=False):
    local_hash = sha256sum(local_path)
    remote_hash = get_remote_sha256(remote_url)
    if local_hash != remote_hash:
        file_name = os.path.basename(local_path)
        if ask_update(file_name):
            print(f"[+] Updating {file_name} ...")
            try:
                urllib.request.urlretrieve(remote_url, local_path)
                print(f"[+] {file_name} updated.")
                if main_script:
                    print("[*] Restarting the script after main file update...")
                    os.execv(sys.executable, [sys.executable] + sys.argv)  # Restart wrapper
            except Exception as e:
                print(f"[!] Error downloading {file_name}: {e}")
        else:
            print(f"[!] {file_name} was NOT updated (update skipped).")
    else:
        print(f"[+] {os.path.basename(local_path)} is up to date.")

# --- AUTO-UPDATE SECTION ---
auto_update(tty2img_path, tty2img_url)
auto_update(script_real, exegolviewer_url, main_script=True)

# --- ENV SETUP ---
if not os.path.exists(venv_path):
    print("[+] Creating virtual environment for Exegol Replay...")
    subprocess.check_call([sys.executable, "-m", "venv", venv_path])

pip = os.path.join(venv_path, "bin", "pip")
try:
    subprocess.check_call([pip, "install", "--upgrade", "pip"])
except subprocess.CalledProcessError:
    print("[!] Error upgrading pip")

dependencies = ["moviepy", "flask", "pyte", "numpy", "Pillow"]
for dep in dependencies:
    try:
        subprocess.check_call([pip, "install", dep])
        print(f"[+] {dep} installed successfully")
    except subprocess.CalledProcessError:
        print(f"[!] Error installing {dep}")

editor_py = os.path.join(
    venv_path, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}",
    "site-packages", "moviepy", "editor.py"
)
if not os.path.exists(editor_py):
    print("[!] moviepy/editor.py missing, patching automatically for compatibility...")
    moviepy_dir = os.path.dirname(editor_py)
    if not os.path.exists(moviepy_dir):
        os.makedirs(moviepy_dir)
    with open(editor_py, "w") as f:
        f.write("from moviepy import *\n")

os.execv(python_path, [python_path, script_real] + sys.argv[1:])
