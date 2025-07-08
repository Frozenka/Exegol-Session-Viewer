#!/usr/bin/env python3
import os
import sys
import threading
import subprocess
import tempfile
import gzip
import json
import re
from flask import Flask, render_template_string, request, send_file, send_from_directory, jsonify
from glob import glob
from datetime import datetime
from collections import defaultdict
import numpy as np

venv_path = os.path.expanduser("~/.venv/exegol-replay")
expected_python = os.path.join(venv_path, "bin", "python3")
required_pkgs = ["flask", "moviepy", "pyte", "numpy", "Pillow"]

def ensure_venv():
    if sys.executable != expected_python and not os.environ.get("IN_VENV"):
        if not os.path.exists(venv_path):
            subprocess.check_call([sys.executable, "-m", "venv", venv_path])
        pip = os.path.join(venv_path, "bin", "pip")
        try:
            subprocess.check_call([pip, "install", "--upgrade", "pip"])
            subprocess.check_call([pip, "install"] + required_pkgs)
        except subprocess.CalledProcessError as e:
            print(f"[!] Error installing dependencies: {e}")
            sys.exit(1)
        os.environ["IN_VENV"] = "1"
        os.execv(expected_python, [expected_python] + sys.argv)
ensure_venv()

import moviepy.editor as mpy
import pyte
import tty2img

app = Flask(__name__, static_folder='.')

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

@app.route("/logo.png")
def logo():
    return send_from_directory('.', 'logo.png')

@app.route("/")
def index():
    base = os.path.expanduser("~/.exegol/workspaces")
    selected = request.args.get("container")
    start = request.args.get("start")
    end = request.args.get("end")
    files, containers = [], set()
    for path in glob(base + "/*/logs/*.asciinema*"):
        container = path.split(os.sep)[-3]
        containers.add(container)
        try:
            open_func = gzip.open if path.endswith(".gz") else open
            with open_func(path, 'rt', errors='ignore') as f:
                line = f.readline()
                header = json.loads(line) if line.startswith('{') else {}
                ts = header.get('timestamp', os.path.getmtime(path))
        except Exception as e:
            print(f"[!] Error reading {path}: {e}")
            ts = os.path.getmtime(path)
        files.append((container, datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S'), path))
    containers = sorted(containers)
    result = []
    if start and end:
        dt_start = datetime.fromisoformat(start)
        dt_end = datetime.fromisoformat(end)
        for c, dts, p in files:
            dt = datetime.strptime(dts, '%Y-%m-%d %H:%M:%S')
            if (not selected or c == selected) and dt_start <= dt <= dt_end:
                result.append((c, dts, p))
    else:
        result = files if not selected else [f for f in files if f[0] == selected]
    grouped = defaultdict(list)
    for c, d, p in sorted(result, key=lambda x: (x[0], x[1]), reverse=True):
        grouped[c].append((d, p))
    return render_template_string("""
<!doctype html><html><head>
<title>Exegol Sessions Viewer</title>
<style>
  body { font-family: sans-serif; background: #111; color: #eee; padding: 20px; }
  .logo { text-align: center; margin-bottom: 10px; }
  .logo img { height: 80px; }
  .content { max-width: 960px; margin: auto; }
  h2 { text-align: center; }
  form { display: flex; justify-content: center; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }
  select, input, button { padding: 6px; border-radius: 5px; border: none; }
  .container-group { background: #222; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 0 8px #333; }
  .container-title { background: #333; padding: 10px; font-weight: bold; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 8px; border-bottom: 1px solid #444; }
  .view-cell { text-align: right; white-space: nowrap; }
  a.view-link, a.download-link { background: #0099cc; color: #fff; padding: 6px 10px; border-radius: 5px; text-decoration: none; margin-left: 5px; }
  a.view-link:hover, a.download-link:hover { background: #0077aa; }
  footer { text-align: center; margin-top: 40px; font-size: 0.9em; color: #777; }
  footer a { color: #aaa; text-decoration: none; font-weight: bold; }
</style></head><body>
<div class="logo"><a href="https://github.com/Frozenka/Exegol-Session-Viewer" target="_blank"><img src="/logo.png" alt="logo"></a></div>
<div class="content">
<form method="get">
  <label>Container:
    <select name="container">
      <option value="">All</option>
      {% for c in containers %}
        <option value="{{c}}" {% if c==selected %}selected{% endif %}>{{c}}</option>
      {% endfor %}
    </select>
  </label>
  <label>Start:
    <input type="datetime-local" name="start" value="{{start or ''}}">
  </label>
  <label>End:
    <input type="datetime-local" name="end" value="{{end or ''}}">
  </label>
  <button type="submit">Search</button>
</form>

{% for container, sessions in grouped.items() %}
<div class="container-group">
  <div class="container-title">{{ container }}</div>
  <table>
    <tr><th>Date</th><th class="view-cell">Action</th></tr>
    {% for date, path in sessions %}
    <tr>
      <td>{{ date }}</td>
      <td class="view-cell">
        <a class="view-link" href="/view?file={{ path }}">🎥 View</a>
        <a class="download-link" href="/view?file={{ path }}&download=1">💾 Download</a>
        <a class="download-link" href="/processing?file={{ path }}" onclick="alert('MP4 generation is experimental and may not work perfectly.');">🎬 Download MP4</a>
      </td>
    </tr>
    {% endfor %}
  </table>
</div>
{% endfor %}
<footer>Made for <a href="https://exegol.com" target="_blank">Exegol</a> with ❤️</footer>
</div></body></html>""", grouped=grouped, containers=containers, selected=selected, start=start, end=end)

@app.route("/view")
def view():
    path = request.args.get("file")
    download_only = request.args.get("download")
    cast_path = convert_to_cast(path)
    container = path.split("/")[-3]
    cast_name = os.path.basename(cast_path)
    if download_only:
        return send_file(cast_path, as_attachment=True, download_name=cast_name)
    title = f"Replay {container} from " + os.path.basename(path).split("_shell")[0].replace("_", " ")
    return f"""<!doctype html><html><head>
<title>Replay</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/asciinema-player@3.0.1/dist/bundle/asciinema-player.css" />
</head><body style="font-family:sans-serif;background:#111;color:#eee;text-align:center">
<div class="logo" style="margin:15px;"><a href="https://github.com/Frozenka/Exegol-Session-Viewer" target="_blank"><img src="/logo.png" style="height:80px;"></a></div>
<h2>{title}</h2>
<div id="player" style="width:80%;max-width:960px;margin:auto;"></div>
<div style="margin-top:1em;">
  <label>Start (MM:SS): <input id="start" type="text" placeholder="00:00" style="width:80px;"></label>
  <label>End (MM:SS): <input id="end" type="text" placeholder="00:44" style="width:80px;"></label>
  <button onclick="downloadExtract()">💾 Download .cast extract</button>
  <button onclick="downloadMP4Extract()">🎬 Download MP4 extract</button>
  <button onclick="downloadFullMP4()">🎬 Download FULL MP4</button>
</div>
<script src="https://cdn.jsdelivr.net/npm/asciinema-player@3.0.1/dist/bundle/asciinema-player.min.js"></script>
<script>
AsciinemaPlayer.create("/raw?file={cast_path}", document.getElementById("player"), {{
  cols: 100, rows: 30, autoplay: true, preload: true, theme: "asciinema"
}});
function parseTime(timeStr) {{
  if (!timeStr) return null;
  const parts = timeStr.split(':');
  if (parts.length === 2) {{
    return parseInt(parts[0]) * 60 + parseInt(parts[1]);
  }}
  return parseFloat(timeStr);
}}
function downloadExtract() {{
  const s = document.getElementById('start').value;
  const e = document.getElementById('end').value;
  let url = `/extract?file={cast_path}`;
  const startSec = parseTime(s);
  const endSec = parseTime(e);
  if (startSec !== null && endSec !== null && endSec > startSec) {{
    url += `&start=${{startSec}}&end=${{endSec}}`;
  }}
  alert(`🎉 The cast file will be downloaded after clicking OK.\\n\\nTo replay it:\\n\\nasciinema play ./` + "{cast_name}" + `\\n\\nMake sure asciinema is installed. This is a .cast recording file.`);
  window.open(url);
}}
function downloadMP4Extract() {{
  const s = document.getElementById('start').value;
  const e = document.getElementById('end').value;
  const startSec = parseTime(s);
  const endSec = parseTime(e);
  if (startSec !== null && endSec !== null && endSec > startSec) {{
    let url = `/extract_mp4?file={path}&start=${{startSec}}&end=${{endSec}}`;
    window.open(url);
  }} else {{
    alert('Please enter valid start and end times (MM:SS format)');
  }}
}}
function downloadFullMP4() {{
  let url = `/processing?file={path}`;
  alert('MP4 generation is experimental and may not work perfectly.');
  window.open(url);
}}
</script>
<footer style="margin-top:30px;font-size:0.9em;color:#777;">Made for <a href="https://exegol.com" target="_blank" style="color:#aaa;font-weight:bold;">Exegol</a> with ❤️</footer>
</body></html>"""

@app.route("/processing")
def processing():
    file = request.args.get("file")
    cast_path = convert_to_cast(file)
    mp4_path = cast_path.replace(".cast", ".mp4")
    progress_path = mp4_path + ".progress"
    if not (os.path.exists(mp4_path) or os.path.exists(progress_path)):
        threading.Thread(target=convert_cast_to_mp4_progress, args=(cast_path, mp4_path, progress_path), daemon=True).start()
    return render_template_string("""
<html><head>
<title>Generating MP4...</title>
<style>
  body { background: #111; color: #eee; font-family: sans-serif; text-align: center; }
  .progress { width: 80%; max-width: 450px; background: #222; border-radius: 20px; margin: 40px auto; padding: 6px;}
  .progress-bar { height: 32px; border-radius: 16px; width: 0; background: linear-gradient(90deg, #00eaff 0%, #00c3ff 100%); transition: width .3s; font-weight: bold; font-size: 1.2em; text-align: center; color: #222; }
  .message { font-size: 1.2em; margin-top: 30px; }
</style>
</head><body>
<div class="logo" style="margin:15px;"><a href="https://github.com/Frozenka/Exegol-Session-Viewer" target="_blank"><img src="/logo.png" style="height:80px;"></a></div>
<div class="message">Generating MP4, please wait...<br>This may take several minutes for long sessions.<br></div>
<div class="progress"><div class="progress-bar" id="bar"></div></div>
<div id="progtxt" style="color:#4df;">Initializing...</div>
<script>
function poll() {
  fetch('/progress?file={{ mp4_path }}')
    .then(r => r.json())
    .then(data => {
      let bar = document.getElementById('bar');
      let progtxt = document.getElementById('progtxt');
      if(data.done) {
        bar.style.width = "100%";
        bar.innerText = "100%";
        progtxt.innerText = "Download starting...";
        setTimeout(function(){
          window.location.href="/download_mp4?file={{ mp4_path }}";
        }, 1000);
      } else {
        let p = Math.floor(data.progress * 100);
        bar.style.width = p + "%";
        bar.innerText = p + "%";
        progtxt.innerText = data.text;
        setTimeout(poll, 1500);
      }
    });
}
setTimeout(poll, 1000);
</script>
<footer style="margin-top:30px;font-size:0.9em;color:#777;">Made for <a href="https://exegol.com" target="_blank" style="color:#aaa;font-weight:bold;">Exegol</a> with ❤️</footer>
</body></html>
    """, mp4_path=mp4_path)

@app.route("/progress")
def progress():
    file = request.args.get("file")
    progress_path = file + ".progress"
    if os.path.exists(file):
        return jsonify({"progress": 1.0, "done": True, "text": "Done!"})
    if os.path.exists(progress_path):
        try:
            with open(progress_path, "r") as f:
                j = json.load(f)
            return jsonify(j)
        except Exception:
            return jsonify({"progress": 0, "done": False, "text": "Waiting..."})
    return jsonify({"progress": 0, "done": False, "text": "Initializing..."})

@app.route("/download_mp4")
def download_mp4():
    file = request.args.get("file")
    if not os.path.exists(file):
        return "File not ready.", 404
    return send_file(file, as_attachment=True, download_name=os.path.basename(file))

@app.route("/raw")
def raw():
    return send_file(request.args.get("file"), mimetype="application/json")

@app.route("/extract")
def extract():
    path = request.args.get("file")
    start = float(request.args.get("start", "0"))
    end = float(request.args.get("end", "999999"))
    with open(path) as f:
        lines = f.readlines()
    header = lines[0]
    body = [json.loads(l) for l in lines[1:] if l.strip() and l.startswith("[")]
    filtered = [e for e in body if start <= e[0] <= end]
    outname = os.path.basename(path).replace(".asciinema.gz", ".cast").replace(".asciinema", ".cast")
    outpath = os.path.join(tempfile.gettempdir(), outname)
    with open(outpath, 'w') as w:
        w.write(header)
        for line in filtered:
            w.write(json.dumps(line) + "\n")
    return send_file(outpath, as_attachment=True, download_name=outname)

@app.route("/extract_mp4")
def extract_mp4():
    file = request.args.get("file")
    start = float(request.args.get("start", "0"))
    end = float(request.args.get("end", "999999"))
    cast_path = convert_to_cast(file)
    mp4_path = cast_path.replace(".cast", f"_extract_{start:.1f}_{end:.1f}.mp4")
    progress_path = mp4_path + ".progress"
    if not (os.path.exists(mp4_path) or os.path.exists(progress_path)):
        threading.Thread(target=convert_cast_to_mp4_progress_extract, args=(cast_path, mp4_path, progress_path, start, end), daemon=True).start()
    return render_template_string("""
<html><head>
<title>Generating MP4 extract...</title>
<style>
  body { background: #111; color: #eee; font-family: sans-serif; text-align: center; }
  .progress { width: 80%; max-width: 450px; background: #222; border-radius: 20px; margin: 40px auto; padding: 6px;}
  .progress-bar { height: 32px; border-radius: 16px; width: 0; background: linear-gradient(90deg, #00eaff 0%, #00c3ff 100%); transition: width .3s; font-weight: bold; font-size: 1.2em; text-align: center; color: #222; }
  .message { font-size: 1.2em; margin-top: 30px; }
</style>
</head><body>
<div class="logo" style="margin:15px;"><a href="https://github.com/Frozenka/Exegol-Session-Viewer" target="_blank"><img src="/logo.png" style="height:80px;"></a></div>
<div class="message">Generating MP4 extract ({{ format_time(start) }} to {{ format_time(end) }}), please wait...<br>This may take several minutes.<br></div>
<div class="progress"><div class="progress-bar" id="bar"></div></div>
<div id="progtxt" style="color:#4df;">Initializing...</div>
<script>
function poll() {
  fetch('/progress?file={{ mp4_path }}')
    .then(r => r.json())
    .then(data => {
      let bar = document.getElementById('bar');
      let progtxt = document.getElementById('progtxt');
      if(data.done) {
        bar.style.width = "100%";
        bar.innerText = "100%";
        progtxt.innerText = "Download starting...";
        setTimeout(function(){
          window.location.href="/download_mp4?file={{ mp4_path }}\";
        }, 1000);
      } else {
        let p = Math.floor(data.progress * 100);
        bar.style.width = p + "%";
        bar.innerText = p + "%";
        progtxt.innerText = data.text;
        setTimeout(poll, 1500);
      }
    });
}
setTimeout(poll, 1000);
</script>
<footer style="margin-top:30px;font-size:0.9em;color:#777;">Made for <a href="https://exegol.com" target="_blank" style="color:#aaa;font-weight:bold;">Exegol</a> with ❤️</footer>
</body></html>
    """, mp4_path=mp4_path, start=start, end=end, format_time=format_time)

def format_time(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"

def convert_to_cast(path):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".cast", mode="w", encoding="utf-8")
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, 'rt', encoding='utf-8', errors='ignore') as f_in:
        try:
            header_line = next(f_in)
        except StopIteration:
            print(f"[!] Fichier vide : {path}")
            tmp.close()
            return tmp.name
        header = {
            "version": 2,
            "width": 100,
            "height": 30,
            "timestamp": int(os.path.getmtime(path)),
            "env": {"TERM": "xterm", "SHELL": "/bin/bash"}
        }
        try:
            maybe_header = json.loads(header_line)
            if isinstance(maybe_header, dict) and "version" in maybe_header:
                header.update(maybe_header)
        except Exception as e:
            print(f"[!] Erreur parsing header: {e}")
        tmp.write(json.dumps(header) + "\n")
        for line in f_in:
            if line.strip().startswith("["):
                try:
                    evt = json.loads(line)
                    if isinstance(evt, list) and evt[1] == "o":
                        if evt[2].strip():
                            tmp.write(json.dumps([evt[0], "o", evt[2]]) + "\n")
                except Exception as e:
                    print(f"[!] Ligne ignorée: {e} : {line[:80]}")
    tmp.close()
    return tmp.name

def convert_cast_to_mp4_progress(cast_path, mp4_path, progress_path):
    try:
        print(f"[DEBUG] Starting MP4 conversion: {cast_path} → {mp4_path}")
        with open(cast_path) as f:
            lines = f.readlines()
        header = json.loads(lines[0])
        events = [json.loads(l) for l in lines[1:] if l.strip() and l.startswith("[")]
        total = len(events)
        width = header.get("width", 100)
        height = header.get("height", 30)
        duration = events[-1][0] if events else 0
        screen = pyte.Screen(width, height)
        stream = pyte.Stream(screen)
        images = []
        timestamps = []
        font_size = 18
        print(f"[DEBUG] Total events: {total}, duration: {duration:.2f}s")
        for i, evt in enumerate(events):
            try:
                stream.feed(evt[2])
                if evt[1] == "o":
                    img = tty2img.tty2img(screen, fontSize=font_size, fgDefaultColor='lime', bgDefaultColor='black')
                    img = img.convert("RGB")
                    images.append(np.array(img))
                    timestamps.append(evt[0])
            except Exception as e:
                print(f"[!] Frame {i} error: {e}")
            if i % 10 == 0 or i == total - 1:
                with open(progress_path, "w") as pf:
                    pf.write(json.dumps({
                        "progress": i / total if total else 1,
                        "done": False,
                        "text": f"Processing frame {i+1}/{total} (t={evt[0]:.1f}s)"
                    }))
        print(f"[DEBUG] Generated {len(images)} frames, timestamps: {timestamps[:10]}")
        if len(timestamps) > 1:
            durations = [s2 - s1 for s1, s2 in zip(timestamps, timestamps[1:])]
            mean_duration = sum(durations) / len(durations)
        else:
            mean_duration = 0.5
        with open(progress_path, "w") as pf:
            pf.write(json.dumps({"progress": 1.0, "done": False, "text": "Encoding MP4..."}))
        if len(images) > 0:
            fps = 1 / mean_duration if mean_duration > 0 else 2
            clip = mpy.ImageSequenceClip(images, fps=fps)
            clip.write_videofile(mp4_path, codec="libx264", fps=fps, audio=False, logger=None)
            print(f"[DEBUG] MP4 file written: {mp4_path}")
            with open(progress_path, "w") as pf:
                pf.write(json.dumps({"progress": 1.0, "done": True, "text": "Done"}))
        else:
            print("[DEBUG] No images generated, skipping video file creation!")
            with open(progress_path, "w") as pf:
                pf.write(json.dumps({"progress": 1.0, "done": True, "text": "No frames generated!"}))
    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        with open(progress_path, "w") as pf:
            pf.write(json.dumps({"progress": 0, "done": False, "text": f"Error: {e}"}))

def convert_cast_to_mp4_progress_extract(cast_path, mp4_path, progress_path, start_time, end_time):
    try:
        print(f"[DEBUG] Starting MP4 extract conversion: {cast_path} → {mp4_path} ({start_time:.1f}s to {end_time:.1f}s)")
        with open(cast_path) as f:
            lines = f.readlines()
        header = json.loads(lines[0])
        events = [json.loads(l) for l in lines[1:] if l.strip() and l.startswith("[")]
        # Filtrer les events par plage temporelle
        filtered_events = [e for e in events if start_time <= e[0] <= end_time]
        # Ajuster les timestamps pour commencer à 0
        if filtered_events:
            time_offset = filtered_events[0][0]
            for e in filtered_events:
                e[0] -= time_offset
        total = len(filtered_events)
        width = header.get("width", 100)
        height = header.get("height", 30)
        duration = filtered_events[-1][0] if filtered_events else 0
        screen = pyte.Screen(width, height)
        stream = pyte.Stream(screen)
        images = []
        timestamps = []
        font_size = 18
        print(f"[DEBUG] Total events: {total}, duration: {duration:.2f}s")
        for i, evt in enumerate(filtered_events):
            try:
                stream.feed(evt[2])
                if evt[1] == "o":
                    img = tty2img.tty2img(screen, fontSize=font_size, fgDefaultColor='lime', bgDefaultColor='black')
                    img = img.convert("RGB")
                    images.append(np.array(img))
                    timestamps.append(evt[0])
            except Exception as e:
                print(f"[!] Frame {i} error: {e}")
            if i % 10 == 0 or i == total - 1:
                with open(progress_path, "w") as pf:
                    pf.write(json.dumps({
                        "progress": i / total if total else 1,
                        "done": False,
                        "text": f"Processing frame {i+1}/{total} (t={evt[0]:.1f}s)"
                    }))
        print(f"[DEBUG] Generated {len(images)} frames, timestamps: {timestamps[:10]}")
        if len(timestamps) > 1:
            durations = [s2 - s1 for s1, s2 in zip(timestamps, timestamps[1:])]
            mean_duration = sum(durations) / len(durations)
        else:
            mean_duration = 0.5
        with open(progress_path, "w") as pf:
            pf.write(json.dumps({"progress": 1.0, "done": False, "text": "Encoding MP4..."}))
        if len(images) > 0:
            fps = 1 / mean_duration if mean_duration > 0 else 2
            clip = mpy.ImageSequenceClip(images, fps=fps)
            clip.write_videofile(mp4_path, codec="libx264", fps=fps, audio=False, logger=None)
            print(f"[DEBUG] MP4 extract file written: {mp4_path}")
            with open(progress_path, "w") as pf:
                pf.write(json.dumps({"progress": 1.0, "done": True, "text": "Done"}))
        else:
            print("[DEBUG] No images generated, skipping video file creation!")
            with open(progress_path, "w") as pf:
                pf.write(json.dumps({"progress": 1.0, "done": True, "text": "No frames generated!"}))
    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        with open(progress_path, "w") as pf:
            pf.write(json.dumps({"progress": 0, "done": False, "text": f"Error: {e}"}))

if __name__ == "__main__":
    print("[+] Exegol Replay running on http://127.0.0.1:5005")
    app.run(debug=False, port=5005)
