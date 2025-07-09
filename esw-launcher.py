#!/usr/bin/env python3
import os, sys, subprocess, urllib.request, hashlib, webbrowser

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

def ask_update():
    while True:
        rep = input("[!] An update for Exegol Session Viewer is available. Do you want to apply it? (Y/n) ").strip().lower()
        if rep in ["", "y", "yes"]:
            return True
        elif rep in ["n", "no"]:
            return False

def auto_update(files):
    # files: list of (local_path, remote_url, main_script_bool)
    needs_update = False
    for local_path, remote_url, main_script in files:
        local_hash = sha256sum(local_path)
        remote_hash = get_remote_sha256(remote_url)
        if local_hash != remote_hash:
            needs_update = True
            break
    if needs_update:
        if ask_update():
            for local_path, remote_url, main_script in files:
                try:
                    print("[+] Updating Exegol Session Viewer ...")
                    urllib.request.urlretrieve(remote_url, local_path)
                    print("[+] Exegol Session Viewer updated.")
                    if main_script:
                        print("[*] Restarting the script after update...")
                        os.execv(sys.executable, [sys.executable] + sys.argv)
                except Exception as e:
                    print(f"[!] Error updating Exegol Session Viewer: {e}")
        else:
            print("[!] Exegol Session Viewer update was skipped.")
    else:
        print("[+] Exegol Session Viewer is up to date.")

# --- AUTO-UPDATE SECTION ---
FILES = [
    (tty2img_path, tty2img_url, False),
    (script_real, exegolviewer_url, True)
]
auto_update(FILES)

# --- ENV SETUP ---
if not os.path.exists(venv_path):
    subprocess.check_call([sys.executable, "-m", "venv", venv_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

pip = os.path.join(venv_path, "bin", "pip")
try:
    subprocess.check_call([pip, "install", "--upgrade", "pip"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except subprocess.CalledProcessError:
    pass

dependencies = ["moviepy", "flask", "pyte", "numpy", "Pillow"]
for dep in dependencies:
    try:
        subprocess.check_call([pip, "install", dep],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        pass

editor_py = os.path.join(
    venv_path, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}",
    "site-packages", "moviepy", "editor.py"
)
if not os.path.exists(editor_py):
    moviepy_dir = os.path.dirname(editor_py)
    if not os.path.exists(moviepy_dir):
        os.makedirs(moviepy_dir)
    with open(editor_py, "w") as f:
        f.write("from moviepy import *\n")

# LAUNCH THE SCRIPT AND PRINT ONLY THE FINAL MESSAGE
def run_and_wait():
    from subprocess import Popen, PIPE, STDOUT
    proc = Popen([python_path, script_real] + sys.argv[1:], stdout=PIPE, stderr=STDOUT, text=True)
    url = None
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            if "Running on http://" in line or "Running on https://" in line:
                url = line.strip().split("Running on ")[-1]
                print(f"Running on {url}")
                break  # On s'arrête dès qu'on a l'URL
        if url:
            ans = input("Do you want to open Exegol Session Viewer in your browser? (Y/n) ").strip().lower()
            if ans in ["", "y", "yes"]:
                webbrowser.open(url)
        for line in proc.stdout:
            pass  # Optionally suppress further output
    except KeyboardInterrupt:
        proc.terminate()

run_and_wait()
