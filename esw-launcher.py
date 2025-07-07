#!/usr/bin/env python3
import os, sys, subprocess, urllib.request

venv_path = os.path.expanduser("~/.venv/exegol-replay")
python_path = os.path.join(venv_path, "bin", "python3")
script_real = os.path.join(os.path.dirname(__file__), "exegolsessionsviewer.py")
tty2img_path = os.path.join(os.path.dirname(__file__), "tty2img.py")
tty2img_url = "https://raw.githubusercontent.com/opcode-eu-org-libs/asciicast2movie/master/tty2img.py"

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

editor_py = os.path.join(venv_path, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages", "moviepy", "editor.py")
if not os.path.exists(editor_py):
    print("[!] moviepy/editor.py missing, patching automatically for compatibility...")
    moviepy_dir = os.path.dirname(editor_py)
    if not os.path.exists(moviepy_dir):
        os.makedirs(moviepy_dir)
    with open(editor_py, "w") as f:
        f.write("from moviepy import *\n")

if not os.path.exists(tty2img_path):
    print("[+] Downloading tty2img.py...")
    try:
        urllib.request.urlretrieve(tty2img_url, tty2img_path)
    except Exception as e:
        print(f"[!] Error downloading tty2img.py: {e}")

os.execv(python_path, [python_path, script_real] + sys.argv[1:])
