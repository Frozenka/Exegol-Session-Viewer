#!/usr/bin/env python3
import os
import sys
import threading
import subprocess
import tempfile
import gzip
import json
import re
import time
from flask import Flask, render_template_string, request, send_file, send_from_directory, jsonify
from glob import glob
from datetime import datetime, timedelta
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

@app.route("/delete_log")
def delete_log():
    path = request.args.get("file")
    if path and os.path.exists(path):
        try:
            os.remove(path)
            return jsonify({"success": True, "message": "Log deleted successfully"})
        except Exception as e:
            return jsonify({"success": False, "message": f"Error deleting log: {e}"})
    return jsonify({"success": False, "message": "Log not found"})

@app.route("/save_comment")
def save_comment():
    path = request.args.get("file")
    comment = request.args.get("comment", "")
    
    if path:
        comment_file = path + ".comment"
        try:
            with open(comment_file, "w", encoding="utf-8") as f:
                f.write(comment)
            return jsonify({"success": True, "message": "Comment saved successfully"})
        except Exception as e:
            return jsonify({"success": False, "message": f"Error saving comment: {e}"})
    return jsonify({"success": False, "message": "Invalid file path"})

@app.route("/get_comment")
def get_comment():
    path = request.args.get("file")
    if path:
        comment_file = path + ".comment"
        if os.path.exists(comment_file):
            try:
                with open(comment_file, "r", encoding="utf-8") as f:
                    comment = f.read()
                return jsonify({"success": True, "comment": comment})
            except Exception as e:
                return jsonify({"success": False, "message": f"Error reading comment: {e}"})
    return jsonify({"success": False, "comment": ""})

@app.route("/")
def index():
    base = os.path.expanduser("~/.exegol/workspaces")
    selected = request.args.get("container")
    start = request.args.get("start")
    end = request.args.get("end")
    files, containers = [], set()
    seen_paths = set()
    
    for path in glob(base + "/*/logs/*.asciinema*"):
        # Ignorer les fichiers .comment
        if path.endswith('.comment'):
            continue
        # Dédupliquer les fichiers .asciinema et .asciinema.gz
        base_path = path.replace('.gz', '')
        if base_path in seen_paths:
            continue
        seen_paths.add(base_path)
        
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
        duration = get_session_duration(path)
        start_dt = datetime.fromtimestamp(ts)
        end_dt = start_dt + timedelta(seconds=duration)
        
        files.append((container, start_dt.strftime('%Y-%m-%d %H:%M:%S'), end_dt.strftime('%Y-%m-%d %H:%M:%S'), path))
    containers = sorted(containers)
    result = []
    if start and end:
        dt_start = datetime.fromisoformat(start)
        dt_end = datetime.fromisoformat(end)
        for c, start_dts, end_dts, p in files:
            dt = datetime.strptime(start_dts, '%Y-%m-%d %H:%M:%S')
            if (not selected or c == selected) and dt_start <= dt <= dt_end:
                result.append((c, start_dts, end_dts, p))
    else:
        result = files if not selected else [f for f in files if f[0] == selected]
    grouped = defaultdict(list)
    seen_sessions = set()
    
    for c, start_d, end_d, p in sorted(result, key=lambda x: (x[0], x[1]), reverse=True):
        # Dédupliquer au niveau session (container + start_time + end_time)
        session_key = f"{c}_{start_d}_{end_d}"
        if session_key in seen_sessions:
            continue
        seen_sessions.add(session_key)
        grouped[c].append((start_d, end_d, p))
    return render_template_string("""
<!doctype html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Exegol Session Manager Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 50%, #16213e 100%);
            color: #e8e8e8;
            min-height: 100vh;
            line-height: 1.6;
        }
        
        .header {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding: 1.5rem 0;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        
        .header-content {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 2rem;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .logo {
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .logo img {
            height: 80px;
            filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.3));
        }
        
        .main-content {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }
        
        .dashboard-header {
            text-align: center;
            margin-bottom: 3rem;
        }
        
        .dashboard-title {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .dashboard-subtitle {
            font-size: 1.1rem;
            color: #a0a0a0;
            font-weight: 300;
        }
        
        .filters-card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        
        .filters-form {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            align-items: end;
        }
        
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }
        
        .form-label {
            font-size: 0.9rem;
            font-weight: 500;
            color: #a0a0a0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .form-input, .form-select {
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            padding: 0.75rem 1rem;
            color: #e8e8e8;
            font-size: 0.95rem;
            transition: all 0.3s ease;
            backdrop-filter: blur(10px);
        }
        
        .form-input:focus, .form-select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            background: rgba(255, 255, 255, 0.15);
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 0.75rem 2rem;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
        }
        
        .container-card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            margin-bottom: 2rem;
            overflow: hidden;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            transition: all 0.3s ease;
        }
        
        .container-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
        }
        
        .container-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 1.5rem 2rem;
            font-size: 1.2rem;
            font-weight: 600;
            color: white;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .accordion-header:hover {
            background: linear-gradient(135deg, #5a6fd8 0%, #6a4190 100%);
        }
        
        .accordion-icon {
            transition: transform 0.3s ease;
        }
        
        .container-content {
            display: block;
        }
        
        .container-content.collapsed {
            display: none;
        }
        
        .comment-section {
            display: flex;
            gap: 0.5rem;
            align-items: flex-start;
        }
        
        .comment-input {
            flex: 1;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 6px;
            padding: 0.5rem;
            color: #e8e8e8;
            font-size: 0.85rem;
            resize: vertical;
            min-height: 40px;
            max-height: 80px;
            font-family: inherit;
        }
        
        .comment-input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.1);
        }
        
        .save-comment-btn {
            padding: 0.5rem;
            min-width: auto;
            height: fit-content;
        }
        
        .container-icon {
            font-size: 1.1rem;
        }
        
        .sessions-table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .sessions-table th {
            background: rgba(255, 255, 255, 0.05);
            padding: 1rem 1.5rem;
            text-align: left;
            font-weight: 600;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #a0a0a0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .sessions-table td {
            padding: 1rem 1.5rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            transition: background 0.3s ease;
        }
        
        .sessions-table tr:hover td {
            background: rgba(255, 255, 255, 0.05);
        }
        
        .session-time {
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
            font-size: 0.9rem;
            color: #a0a0a0;
        }
        
        .actions-group {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }
        
        .btn {
            padding: 0.5rem 1rem;
            border-radius: 6px;
            text-decoration: none;
            font-size: 0.85rem;
            font-weight: 500;
            transition: all 0.3s ease;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            border: none;
            cursor: pointer;
        }
        
        .btn-view {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
        }
        
        .btn-download {
            background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
            color: white;
        }
        
        .btn-mp4 {
            background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            color: white;
        }
        
        .btn-danger {
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
            color: white;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }
        
        .footer {
            text-align: center;
            padding: 2rem;
            color: #a0a0a0;
            font-size: 0.9rem;
        }
        
        .footer a {
            color: #667eea;
            text-decoration: none;
            font-weight: 500;
        }
        
        .footer a:hover {
            text-decoration: underline;
        }
        
        @media (max-width: 768px) {
            .main-content {
                padding: 1rem;
            }
            
            .dashboard-title {
                font-size: 2rem;
            }
            
            .filters-form {
                grid-template-columns: 1fr;
            }
            
            .actions-group {
                flex-direction: column;
            }
            
            .btn {
                justify-content: center;
            }
        }
    </style>
</head>
<body>
    <header class="header">
        <div class="header-content">
            <div class="logo">
                <img src="/logo.png" alt="Exegol">
            </div>
        </div>
    </header>
    
    <main class="main-content">
        <div class="dashboard-header">
            <h1 class="dashboard-title">Session Dashboard</h1>
        </div>
        
        <div class="filters-card">
            <form method="get" class="filters-form">
                <div class="form-group">
                    <label class="form-label">Container</label>
                    <select name="container" class="form-select">
                        <option value="">All containers</option>
                        {% for c in containers %}
                        <option value="{{c}}" {% if c==selected %}selected{% endif %}>{{c}}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Start Date</label>
                    <input type="datetime-local" name="start" value="{{start or ''}}" class="form-input">
                </div>
                <div class="form-group">
                    <label class="form-label">End Date</label>
                    <input type="datetime-local" name="end" value="{{end or ''}}" class="form-input">
                </div>
                <div class="form-group">
                    <button type="submit" class="btn-primary">
                        <i class="fas fa-filter"></i> Apply Filters
                    </button>
                </div>
            </form>
        </div>
        
        {% for container, sessions in grouped.items() %}
        <div class="container-card">
            <div class="container-header accordion-header" onclick="toggleContainer('{{ container|replace(' ', '_')|replace('-', '_')|replace('.', '_') }}')">
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <i class="fas fa-chevron-down accordion-icon" id="icon-{{ container|replace(' ', '_')|replace('-', '_')|replace('.', '_') }}" style="transform: rotate(-90deg);"></i>
                    <i class="fas fa-server container-icon"></i>
                    {{ container }}
                </div>
            </div>
            <div class="container-content collapsed" id="content-{{ container|replace(' ', '_')|replace('-', '_')|replace('.', '_') }}">
                <table class="sessions-table">
                    <thead>
                        <tr>
                            <th>Start Time</th>
                            <th>End Time</th>
                            <th>Comment</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for start_date, end_date, path in sessions %}
                        <tr>
                            <td class="session-time">{{ start_date }}</td>
                            <td class="session-time">{{ end_date }}</td>
                            <td>
                                <div class="comment-section">
                                    <textarea class="comment-input" placeholder="Add a comment..." data-file="{{ path }}" id="comment-{{ path|replace('/', '_')|replace('.', '_') }}" value=""></textarea>
                                    <button class="btn btn-primary save-comment-btn" onclick="saveComment('{{ path }}')">
                                        <i class="fas fa-save"></i>
                                    </button>
                                </div>
                            </td>
                            <td>
                                <div class="actions-group">
                                    <a class="btn btn-view" href="/view?file={{ path }}">
                                        <i class="fas fa-play"></i> View
                                    </a>
                                    <a class="btn btn-download" href="/view?file={{ path }}&download=1">
                                        <i class="fas fa-download"></i> Download
                                    </a>
                                    <a class="btn btn-mp4" href="/processing?file={{ path }}" onclick="alert('Full MP4 generation is very long.');">
                                        <i class="fas fa-video"></i> MP4
                                    </a>
                                    <button type="button" class="btn btn-danger" onclick="deleteLog('{{ path }}'); return false;">
                                        <i class="fas fa-trash"></i> Delete
                                    </button>
                                </div>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        {% endfor %}
    </main>
    
    <footer class="footer">
        <div style="text-align: center; padding: 2rem; color: #a0a0a0; font-size: 0.9rem;">
            Made for <a href="https://exegol.com" target="_blank" style="color: #667eea; text-decoration: none; font-weight: 500;">Exegol</a> with ❤️
        </div>
    </footer>
    
    <script>
        // Accordion functionality
        function toggleContainer(containerId) {
            console.log('toggleContainer called with:', containerId);
            const content = document.getElementById('content-' + containerId);
            const icon = document.getElementById('icon-' + containerId);
            
            console.log('content element:', content);
            console.log('icon element:', icon);
            
            if (content.classList.contains('collapsed')) {
                content.classList.remove('collapsed');
                icon.style.transform = 'rotate(0deg)';
                localStorage.setItem('lastOpenAccordion', containerId);
                console.log('Expanded container');
            } else {
                content.classList.add('collapsed');
                icon.style.transform = 'rotate(-90deg)';
                localStorage.removeItem('lastOpenAccordion');
                console.log('Collapsed container');
            }
        }
        
        // Delete log functionality
        function deleteLog(filePath) {
            console.log('deleteLog called with:', filePath);
            event.preventDefault();
            event.stopPropagation();
            
            if (confirm('⚠️ WARNING: This will permanently delete the log file!\\n\\nThis action cannot be undone. Are you sure you want to delete this log?')) {
                console.log('User confirmed deletion');
                fetch('/delete_log?file=' + encodeURIComponent(filePath))
                    .then(response => response.json())
                    .then(data => {
                        console.log('Delete response:', data);
                        if (data.success) {
                            alert('✅ Log deleted successfully');
                            location.reload();
                        } else {
                            alert('❌ Error: ' + data.message);
                        }
                    })
                    .catch(error => {
                        console.error('Delete error:', error);
                        alert('❌ Error: ' + error);
                    });
            }
        }
        
        // Save comment functionality
        function saveComment(filePath) {
            console.log('saveComment called with:', filePath);
            const commentId = 'comment-' + filePath.replace(/\//g, '_').replace(/\./g, '_');
            const commentInput = document.getElementById(commentId);
            if (!commentInput) {
                console.error('Could not find comment input for:', filePath, 'id:', commentId);
                return;
            }
            const comment = commentInput.value;
            
            console.log('Comment input element:', commentInput);
            console.log('Comment value:', comment);
            
            fetch('/save_comment?file=' + encodeURIComponent(filePath) + '&comment=' + encodeURIComponent(comment))
                .then(response => response.json())
                .then(data => {
                    console.log('Save comment response:', data);
                    if (data.success) {
                        // Show success feedback
                        const btn = commentInput.nextElementSibling;
                        const originalHTML = btn.innerHTML;
                        btn.innerHTML = '<i class="fas fa-check"></i>';
                        btn.style.background = 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)';
                        
                        setTimeout(() => {
                            btn.innerHTML = originalHTML;
                            btn.style.background = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';
                        }, 2000);
                    } else {
                        alert('❌ Error: ' + data.message);
                    }
                })
                .catch(error => {
                    console.error('Save comment error:', error);
                    alert('❌ Error: ' + error);
                });
        }
        
        // Load comments on page load
        document.addEventListener('DOMContentLoaded', function() {
            // Restore last open accordion
            const lastOpenAccordion = localStorage.getItem('lastOpenAccordion');
            if (lastOpenAccordion) {
                const content = document.getElementById('content-' + lastOpenAccordion);
                const icon = document.getElementById('icon-' + lastOpenAccordion);
                if (content && icon) {
                    content.classList.remove('collapsed');
                    icon.style.transform = 'rotate(0deg)';
                    console.log('Restored open accordion:', lastOpenAccordion);
                }
            }
            
            // Load comments
            const commentInputs = document.querySelectorAll('.comment-input');
            commentInputs.forEach((input, index) => {
                const filePath = input.getAttribute('data-file');
                const commentId = input.id;
                console.log('Loading comment for:', filePath, 'index:', index, 'id:', commentId);
                
                // Store the input element reference
                const currentInput = input;
                
                fetch('/get_comment?file=' + encodeURIComponent(filePath))
                    .then(response => response.json())
                    .then(data => {
                        console.log('Comment data for', filePath, ':', data);
                        if (data.success && data.comment) {
                            // Use the stored reference instead of re-querying
                            currentInput.value = data.comment;
                            console.log('Set comment for', filePath, ':', data.comment);
                        } else {
                            // Ensure empty value for new comments
                            currentInput.value = '';
                            console.log('Set empty comment for', filePath);
                        }
                    })
                    .catch(error => {
                        console.log('Error loading comment for', filePath, ':', error);
                        // Ensure empty value on error
                        currentInput.value = '';
                    });
            });
        });
    </script>
</body>
</html>
""", grouped=grouped, containers=containers, selected=selected, start=start, end=end)

@app.route("/view")
def view():
    path = request.args.get("file")
    download_only = request.args.get("download")
    start_time = request.args.get("start_time", "0")
    cast_path = convert_to_cast(path)
    container = path.split("/")[-3]
    cast_name = os.path.basename(cast_path)
    if download_only:
        return send_file(cast_path, as_attachment=True, download_name=cast_name)
    title = f"Replay {container} from " + os.path.basename(path).split("_shell")[0].replace("_", " ")
    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Session Player Pro - {title}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/asciinema-player@3.0.1/dist/bundle/asciinema-player.css" />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 50%, #16213e 100%);
            color: #e8e8e8;
            min-height: 100vh;
            line-height: 1.6;
        }}
        
        .header {{
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding: 1rem 0;
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        
        .header-content {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 2rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        
        .logo {{
            display: flex;
            align-items: center;
            gap: 1rem;
        }}
        
        .logo img {{
            height: 40px;
            filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.3));
        }}
        
        .logo-text {{
            font-size: 1.2rem;
            font-weight: 600;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .btn-back {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 25px;
            padding: 0.75rem 1.5rem;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
        }}
        
        .btn-back:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
        }}
        
        .view-header-content {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 2rem;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
        }}
        
        .view-logo {{
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        
        .view-logo img {{
            height: 80px;
            filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.3));
        }}
        
        .view-back-btn {{
            position: absolute;
            right: 2rem;
        }}
        
        .main-content {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }}
        
        .session-header {{
            text-align: center;
            margin-bottom: 2rem;
        }}
        
        .session-title {{
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .player-section {{
            display: grid;
            grid-template-columns: 1fr 320px;
            gap: 2rem;
            margin-bottom: 2rem;
        }}
        
        .player-container {{
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 2rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }}
        
        #player {{
            width: 100%;
            max-width: 100%;
            margin: 0 auto;
        }}
        
        .controls-sidebar {{
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }}
        
        .control-card {{
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
        }}
        
        .control-group {{
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }}
        
        .control-title {{
            font-size: 1.1rem;
            font-weight: 600;
            color: #a0a0a0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.5rem;
        }}
        
        .time-inputs {{
            display: flex;
            gap: 1rem;
            align-items: center;
            flex-wrap: wrap;
        }}
        
        .time-input {{
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            padding: 0.75rem 1rem;
            color: #e8e8e8;
            font-size: 0.95rem;
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
            transition: all 0.3s ease;
            backdrop-filter: blur(10px);
            width: 120px;
        }}
        
        .time-input:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            background: rgba(255, 255, 255, 0.15);
        }}
        
        .btn {{
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            text-decoration: none;
            font-size: 0.9rem;
            font-weight: 600;
            transition: all 0.3s ease;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            border: none;
            cursor: pointer;
            color: white;
        }}
        
        .btn-primary {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}
        
        .btn-success {{
            background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
        }}
        
        .btn-warning {{
            background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
        }}
        
        .btn-danger {{
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
        }}
        
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }}
        
        .search-container {{
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }}
        
        .search-box {{
            display: flex;
            gap: 1rem;
            align-items: center;
            margin-bottom: 1rem;
        }}
        
        .search-input {{
            flex: 1;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            padding: 0.75rem 1rem;
            color: #e8e8e8;
            font-size: 0.95rem;
            transition: all 0.3s ease;
            backdrop-filter: blur(10px);
        }}
        
        .search-input:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            background: rgba(255, 255, 255, 0.15);
        }}
        
        .search-results {{
            max-height: 300px;
            overflow-y: auto;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 1rem;
            margin-top: 1rem;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        
        .search-result {{
            padding: 1rem;
            margin: 0.5rem 0;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            cursor: pointer;
            border-left: 4px solid #667eea;
            transition: all 0.3s ease;
        }}
        
        .search-result:hover {{
            background: rgba(255, 255, 255, 0.1);
            transform: translateX(5px);
        }}
        

        
        .search-info {{
            text-align: center;
            color: #a0a0a0;
            font-size: 0.9rem;
            margin-top: 1rem;
            padding: 0.5rem;
            border-radius: 6px;
        }}
        
        .search-info.success {{
            background: rgba(76, 175, 80, 0.1);
            color: #4CAF50;
            border: 1px solid rgba(76, 175, 80, 0.3);
        }}
        
        .search-info.error {{
            background: rgba(244, 67, 54, 0.1);
            color: #f44336;
            border: 1px solid rgba(244, 67, 54, 0.3);
        }}
        
        .search-info.no-results {{
            background: rgba(255, 152, 0, 0.1);
            color: #ff9800;
            border: 1px solid rgba(255, 152, 0, 0.3);
        }}
        
        .cut-container {{
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }}
        
        .cut-buttons {{
            display: flex;
            gap: 1rem;
            justify-content: center;
            flex-wrap: wrap;
        }}
        
        .cut-info {{
            text-align: center;
            color: #a0a0a0;
            font-size: 0.9rem;
            margin-top: 1rem;
            padding: 0.5rem;
            border-radius: 6px;
        }}
        
        .nav-overlay {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            z-index: 9999;
            justify-content: center;
            align-items: center;
        }}
        
        .nav-overlay-content {{
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 16px;
            padding: 3rem;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
        }}
        
        .spinner {{
            width: 50px;
            height: 50px;
            border: 4px solid #667eea;
            border-top: 4px solid transparent;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 1.5rem;
        }}
        
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
        
        @media (max-width: 768px) {{
            .main-content {{
                padding: 1rem;
            }}
            
            .session-title {{
                font-size: 1.5rem;
            }}
            
            .player-section {{
                grid-template-columns: 1fr;
            }}
            
            .time-inputs {{
                flex-direction: column;
                align-items: stretch;
            }}
            
            .time-input {{
                width: 100%;
            }}
            
            .search-box {{
                flex-direction: column;
            }}
        }}
    </style>
</head>
<body>
    <header class="header">
        <div class="view-header-content">
            <div class="view-logo">
                <a href="https://github.com/Frozenka/Exegol-Session-Viewer" target="_blank">
                    <img src="/logo.png" alt="Exegol">
                </a>
            </div>
            <a href="/" class="btn-back view-back-btn">
                <i class="fas fa-home"></i> Back to Dashboard
            </a>
        </div>
    </header>
    
    <main class="main-content">
        <div class="session-header">
            <h1 class="session-title">{title}</h1>
        </div>
        
        <div class="player-section">
            <div class="player-container">
                <div id="player"></div>
            </div>
            
            <div class="controls-sidebar">
                <div class="control-card">
                    <div class="control-title">Extract Controls</div>
                    <div class="time-inputs">
                        <label>Start Time:
                            <input id="start" type="text" placeholder="00:00" class="time-input">
                        </label>
                        <label>End Time:
                            <input id="end" type="text" placeholder="00:00" class="time-input">
                        </label>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 0.5rem; margin-top: 1rem;">
                        <button onclick="downloadExtract()" class="btn btn-primary">
                            <i class="fas fa-download"></i> Download .cast
                        </button>
                        <button onclick="downloadMP4Extract()" class="btn btn-success">
                            <i class="fas fa-video"></i> Download MP4 Extract
                        </button>
                        <button onclick="downloadFullMP4()" class="btn btn-warning">
                            <i class="fas fa-film"></i> Download Full MP4
                        </button>
                    </div>
                </div>
                
                <div class="control-card">
                    <div class="control-title">Cut Points</div>
                    <div style="display: flex; flex-direction: column; gap: 0.5rem;">
                        <button onclick="setStartTime()" class="btn btn-success">
                            <i class="fas fa-flag"></i> Set Start Point
                        </button>
                        <button onclick="setEndTime()" class="btn btn-warning">
                            <i class="fas fa-flag-checkered"></i> Set End Point
                        </button>
                    </div>
                    <div class="cut-info">
                        Click "Set Start Point" then "Set End Point" during playback to mark cut points
                    </div>
                </div>
            </div>
        </div>
        
        <div class="search-container">
            <div class="control-title">Content Search</div>
            <div class="search-box">
                <input type="text" id="searchInput" class="search-input" placeholder="Search in session content..." onkeypress="if(event.key==='Enter') searchContent()">
                <button onclick="searchContent()" class="btn btn-primary" id="searchBtn">
                    <i class="fas fa-search"></i> Search
                </button>
            </div>
            <div id="searchResults" class="search-results" style="display:none;"></div>

            <div id="searchInfo" class="search-info"></div>
        </div>
    </main>
    
    <div id="navOverlay" class="nav-overlay">
        <div class="nav-overlay-content">
            <div class="spinner"></div>
            <div style="color:#fff; font-size:1.2rem; font-weight:600; margin-bottom:0.5rem;">Loading...</div>
            <div style="color:#a0a0a0; font-size:0.9rem;">Navigating to selected moment</div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/asciinema-player@3.0.1/dist/bundle/asciinema-player.min.js"></script>
    <script>
        let searchResults = [];
        let currentResultIndex = 0;
        let currentPlayerTime = 0;

        const player = AsciinemaPlayer.create("/raw?file={cast_path}", document.getElementById("player"), {{
            cols: 100, rows: 30, autoplay: false, preload: true, theme: "asciinema", startAt: {start_time}
}});

// Store player instance globally for access by other functions
window.playerInstance = player;

// Initialize current time when player is ready
setTimeout(() => {{
  const playerElement = document.querySelector('#player asciinema-player');
  if (playerElement) {{
    if (playerElement.currentTime !== undefined) {{
      currentPlayerTime = playerElement.currentTime;
    }} else if (playerElement.getCurrentTime && typeof playerElement.getCurrentTime === 'function') {{
      currentPlayerTime = playerElement.getCurrentTime();
    }} else if (playerElement._player && playerElement._player.getCurrentTime) {{
      currentPlayerTime = playerElement._player.getCurrentTime();
    }}
  }}
}}, 2000);

// Update current time every second
setInterval(() => {{
  const playerElement = document.querySelector('#player asciinema-player');
  if (playerElement) {{
    if (playerElement.currentTime !== undefined) {{
      currentPlayerTime = playerElement.currentTime;
    }} else if (playerElement.getCurrentTime && typeof playerElement.getCurrentTime === 'function') {{
      currentPlayerTime = playerElement.getCurrentTime();
    }} else if (playerElement._player && playerElement._player.getCurrentTime) {{
      currentPlayerTime = playerElement._player.getCurrentTime();
    }}
  }}
  console.log('Current player time:', currentPlayerTime); // Debug
}}, 500);

// Functions to set cut points
function setStartTime() {{
  // Try to get current time from the global player instance
  let currentTime = 0;
  
  if (window.playerInstance) {{
    try {{
      currentTime = window.playerInstance.getCurrentTime();
      console.log('Set Start clicked, using playerInstance:', currentTime);
    }} catch (e) {{
      console.log('Error getting time from playerInstance:', e);
    }}
  }}
  
  // Fallback: try to get from DOM element
  if (currentTime === 0) {{
    const playerElement = document.querySelector('#player asciinema-player');
    if (playerElement) {{
      try {{
        // Try different methods to get current time
        if (playerElement.currentTime !== undefined) {{
          currentTime = playerElement.currentTime;
        }} else if (playerElement.getCurrentTime && typeof playerElement.getCurrentTime === 'function') {{
          currentTime = playerElement.getCurrentTime();
        }} else if (playerElement._player && playerElement._player.getCurrentTime) {{
          currentTime = playerElement._player.getCurrentTime();
        }}
        console.log('Set Start clicked, using DOM element:', currentTime);
      }} catch (e) {{
        console.log('Error getting time from DOM element:', e);
      }}
    }}
  }}
  
  console.log('Set Start clicked, final currentTime:', currentTime);
  document.getElementById('start').value = formatTime(currentTime);
  showCutInfo(`Start point set to ${{formatTime(currentTime)}}`, 'success');
}}

function setEndTime() {{
  // Try to get current time from the global player instance
  let currentTime = 0;
  
  if (window.playerInstance) {{
    try {{
      currentTime = window.playerInstance.getCurrentTime();
      console.log('Set End clicked, using playerInstance:', currentTime);
    }} catch (e) {{
      console.log('Error getting time from playerInstance:', e);
    }}
  }}
  
  // Fallback: try to get from DOM element
  if (currentTime === 0) {{
    const playerElement = document.querySelector('#player asciinema-player');
    if (playerElement) {{
      try {{
        // Try different methods to get current time
        if (playerElement.currentTime !== undefined) {{
          currentTime = playerElement.currentTime;
        }} else if (playerElement.getCurrentTime && typeof playerElement.getCurrentTime === 'function') {{
          currentTime = playerElement.getCurrentTime();
        }} else if (playerElement._player && playerElement._player.getCurrentTime) {{
          currentTime = playerElement._player.getCurrentTime();
        }}
        console.log('Set End clicked, using DOM element:', currentTime);
      }} catch (e) {{
        console.log('Error getting time from DOM element:', e);
      }}
    }}
  }}
  
  console.log('Set End clicked, final currentTime:', currentTime);
  document.getElementById('end').value = formatTime(currentTime);
  showCutInfo(`End point set to ${{formatTime(currentTime)}}`, 'success');
}}

function showCutInfo(message, type) {{
  const cutContainer = document.querySelector('.cut-container');
  let infoDiv = cutContainer.querySelector('.cut-info');
  if (!infoDiv) {{
    infoDiv = document.createElement('div');
    infoDiv.className = 'cut-info';
    infoDiv.style.cssText = 'text-align:center;margin-top:10px;font-size:0.9em;';
    cutContainer.appendChild(infoDiv);
  }}
  infoDiv.textContent = message;
  infoDiv.style.color = type === 'success' ? '#4CAF50' : '#f44336';
  setTimeout(() => {{
    infoDiv.textContent = '';
  }}, 3000);
}}

// Search function
function searchContent() {{
  const query = document.getElementById('searchInput').value.trim();
  if (!query) {{
    hideSearchResults();
    return;
  }}
  
  // Show loading animation on search button
  const searchBtn = document.getElementById('searchBtn');
  const originalText = searchBtn.innerHTML;
  searchBtn.innerHTML = '⏳ Searching...';
  searchBtn.disabled = true;
  
  fetch(`/search?file={path}&q=${{encodeURIComponent(query)}}`)
    .then(response => response.json())
    .then(data => {{
      // Restore search button
      searchBtn.innerHTML = originalText;
      searchBtn.disabled = false;
      
      if (data.error) {{
        showSearchInfo(`Error: ${{data.error}}`, 'error');
        return;
      }}
      
      searchResults = data.results;
      currentResultIndex = 0;
      
      if (searchResults.length === 0) {{
        showSearchInfo(`No results found for "${{query}}"`, 'no-results');
        hideSearchResults();
      }} else {{
        showSearchInfo(`${{searchResults.length}} result(s) found for "${{query}}"`, 'success');
        displaySearchResults();
      }}
    }})
    .catch(error => {{
      // Restore search button
      searchBtn.innerHTML = originalText;
      searchBtn.disabled = false;
      showSearchInfo(`Search error: ${{error}}`, 'error');
    }});
}}

// Display search results
function displaySearchResults() {{
  const resultsDiv = document.getElementById('searchResults');
  const navDiv = document.getElementById('searchNav');
  
  resultsDiv.innerHTML = '';
  searchResults.forEach((result, index) => {{
    const resultDiv = document.createElement('div');
    resultDiv.className = 'search-result';
    resultDiv.innerHTML = `
      <div style="font-weight: bold; display: flex; justify-content: space-between; align-items: center;">
        <span>⏱️ Time: ${{formatTime(result.timestamp)}}</span>
        <span style="font-size: 0.8em; color: #0099cc;">Click to go to this moment</span>
      </div>
      <div style="font-size: 0.9em; color: #ccc; margin-top: 5px;">${{result.content}}</div>
    `;
    resultDiv.onclick = () => {{
      goToResult(index);
      // Visual effect to confirm click
      resultDiv.style.transform = 'scale(0.98)';
      setTimeout(() => {{
        resultDiv.style.transform = 'scale(1)';
      }}, 150);
    }};
    resultsDiv.appendChild(resultDiv);
  }});
  
  resultsDiv.style.display = 'block';
}}



// Go to specific result
function goToResult(index) {{
  if (index < 0 || index >= searchResults.length) return;
  
  currentResultIndex = index;
  const result = searchResults[index];
  
  // Update result display
  const resultElements = document.querySelectorAll('.search-result');
  resultElements.forEach((el, i) => {{
    el.classList.toggle('active', i === index);
  }});
  
  // Show overlay for 5 seconds
  const overlay = document.getElementById('navOverlay');
  overlay.style.display = 'flex';
  
  // Reload page with timestamp parameter after 5 seconds
  setTimeout(() => {{
    const currentUrl = new URL(window.location);
    currentUrl.searchParams.set('start_time', result.timestamp);
    window.location.href = currentUrl.toString();
  }}, 5000);
}}



// Display search information
function showSearchInfo(message, type) {{
  const infoDiv = document.getElementById('searchInfo');
  infoDiv.textContent = message;
  infoDiv.className = `search-info ${{type}}`;
}}

// Hide search results
function hideSearchResults() {{
  document.getElementById('searchResults').style.display = 'none';
  document.getElementById('searchNav').style.display = 'none';
  document.getElementById('searchInfo').textContent = '';
}}

// Formater le temps en MM:SS
function formatTime(seconds) {{
  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${{minutes.toString().padStart(2, '0')}}:${{secs.toString().padStart(2, '0')}}`;
}}

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
  alert('MP4 generation is verry long.');
  window.open(url);
}}
</script>

<script>
</script>

<footer style="margin-top:30px;font-size:0.9em;color:#777;text-align:center;">Made for <a href="https://exegol.com" target="_blank" style="color:#aaa;font-weight:bold;">Exegol</a> with ❤️</footer>
</body></html>"""

@app.route("/processing")
def processing():
    file = request.args.get("file")
    print(f"[DEBUG] Processing request for file: {file}")
    
    cast_path = convert_to_cast(file)
    print(f"[DEBUG] Cast path: {cast_path}")
    
    mp4_path = cast_path.replace(".cast", ".mp4")
    progress_path = mp4_path + ".progress"
    
    print(f"[DEBUG] MP4 path: {mp4_path}")
    print(f"[DEBUG] Progress path: {progress_path}")
    print(f"[DEBUG] MP4 exists: {os.path.exists(mp4_path)}")
    print(f"[DEBUG] Progress exists: {os.path.exists(progress_path)}")
    
    if not (os.path.exists(mp4_path) or os.path.exists(progress_path)):
        print(f"[DEBUG] Starting conversion thread...")
        try:
            thread = threading.Thread(target=convert_cast_to_mp4_progress, args=(cast_path, mp4_path, progress_path), daemon=True)
            thread.start()
            print(f"[DEBUG] Thread started successfully")
        except Exception as e:
            print(f"[DEBUG] Error starting thread: {e}")
            # Create initial progress file to show error
            with open(progress_path, "w") as pf:
                pf.write(json.dumps({"progress": 0, "done": False, "text": f"Error starting conversion: {e}"}))
    else:
        print(f"[DEBUG] File already exists or conversion in progress")
    
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
    
    print(f"[DEBUG] Progress check - File: {file}")
    print(f"[DEBUG] Progress check - File exists: {os.path.exists(file)}")
    print(f"[DEBUG] Progress check - Progress exists: {os.path.exists(progress_path)}")
    
    if os.path.exists(file):
        print(f"[DEBUG] Progress check - File ready, returning done")
        return jsonify({"progress": 1.0, "done": True, "text": "Done!"})
    if os.path.exists(progress_path):
        try:
            with open(progress_path, "r") as f:
                j = json.load(f)
            print(f"[DEBUG] Progress check - Progress data: {j}")
            return jsonify(j)
        except Exception as e:
            print(f"[DEBUG] Progress check - Error reading progress: {e}")
            return jsonify({"progress": 0, "done": False, "text": "Waiting..."})
    print(f"[DEBUG] Progress check - No file or progress, returning initializing")
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
    """, mp4_path=mp4_path, start=start, end=end, format_time=format_time)

@app.route("/search")
def search():
    path = request.args.get("file")
    query = request.args.get("q", "")
    cast_path = convert_to_cast(path)
    
    if not query:
        return jsonify({"results": [], "total": 0})
    
    try:
        with open(cast_path) as f:
            lines = f.readlines()
        
        header = json.loads(lines[0])
        events = []
        search_results = []
        
        for i, line in enumerate(lines[1:], 1):
            if line.strip().startswith("["):
                try:
                    evt = json.loads(line)
                    if isinstance(evt, list) and len(evt) >= 3 and evt[1] == "o":
                        events.append(evt)
                        # Search in output content
                        if query.lower() in evt[2].lower():
                            search_results.append({
                                "index": len(events) - 1,
                                "timestamp": evt[0],
                                "content": evt[2][:100] + "..." if len(evt[2]) > 100 else evt[2],
                                "line_number": i
                            })
                except Exception:
                    continue
        
        return jsonify({
            "results": search_results,
            "total": len(search_results),
            "query": query
        })
        
    except Exception as e:
        return jsonify({"error": str(e), "results": [], "total": 0})

def get_session_duration(path):
    """Calculate session duration by reading the asciinema file"""
    try:
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, 'rt', encoding='utf-8', errors='ignore') as f_in:
            next(f_in, None)
            events = []
            for line in f_in:
                if line.strip().startswith("["):
                    try:
                        evt = json.loads(line)
                        if isinstance(evt, list) and len(evt) >= 3:
                            events.append(evt[0])  # timestamp
                    except Exception:
                        continue
            if len(events) >= 2:
                return events[-1] - events[0]
            return 0
    except Exception as e:
        print(f"[!] Error calculating session duration {path}: {e}")
        return 0

def format_time(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"



def convert_to_cast(path):
    """Convert asciinema file to cast format with validation and cleaning"""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".cast", mode="w", encoding="utf-8")
    opener = gzip.open if path.endswith(".gz") else open
    
    with opener(path, 'rt', encoding='utf-8', errors='ignore') as f_in:
        try:
            header_line = next(f_in)
        except StopIteration:
            print(f"[!] Empty file: {path}")
            tmp.close()
            return tmp.name
        
        # Parse and validate header
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
            print(f"[!] Header parsing error: {e}")
        
        # Write header
        tmp.write(json.dumps(header) + "\n")
        
        # Parse all events first
        events = []
        for line in f_in:
            if line.strip().startswith("["):
                try:
                    evt = json.loads(line)
                    if isinstance(evt, list) and len(evt) >= 3:
                        events.append(evt)
                except Exception as e:
                    print(f"[!] Ignored line: {e} : {line[:80]}")
        
        # Write events directly
        for event in events:
            tmp.write(json.dumps(event) + "\n")
    
    tmp.close()
    return tmp.name

def get_exegol_colors():
    """Get the exact colors used by Exegol terminal theme"""
    return {
        'fg': 'magenta',  # Exegol uses magenta for main commands
        'bg': 'black'     # Dark background like Exegol
    }

def clean_color_for_tty2img(color):
    """Convert any color format to a format supported by tty2img"""
    if not color:
        return 'white'
    
    color_str = str(color).lower().strip()
    
    # Handle hex colors
    if color_str.startswith('#'):
        # Convert common hex colors to named colors
        hex_to_name = {
            '#000000': 'black',
            '#ffffff': 'white',
            '#ff0000': 'red',
            '#00ff00': 'green',
            '#0000ff': 'blue',
            '#ffff00': 'yellow',
            '#ff00ff': 'magenta',
            '#00ffff': 'cyan',
            '#808080': 'gray',
            '#c0c0c0': 'lightgray',
            '#800000': 'darkred',
            '#008000': 'darkgreen',
            '#000080': 'darkblue',
            '#808000': 'darkyellow',
            '#800080': 'darkmagenta',
            '#008080': 'darkcyan'
        }
        return hex_to_name.get(color_str, 'white')
    
    # Handle bright colors
    if 'bright' in color_str:
        color_map = {
            'brightblack': 'gray',
            'brightred': 'red',
            'brightgreen': 'green',
            'brightyellow': 'yellow',
            'brightblue': 'blue',
            'brightmagenta': 'magenta',
            'brightcyan': 'cyan',
            'brightwhite': 'white'
        }
        return color_map.get(color_str, 'white')
    
    # Handle standard colors
    standard_colors = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white', 'gray']
    if color_str in standard_colors:
        return color_str
    
    # Default fallback
    return 'white'

def convert_cast_to_mp4_progress(cast_path, mp4_path, progress_path):
    print(f"[DEBUG] === CONVERSION THREAD STARTED ===")
    print(f"[DEBUG] Thread ID: {threading.current_thread().ident}")
    print(f"[DEBUG] Cast path: {cast_path}")
    print(f"[DEBUG] MP4 path: {mp4_path}")
    print(f"[DEBUG] Progress path: {progress_path}")
    
    try:
        print(f"[DEBUG] Starting MP4 conversion: {cast_path} → {mp4_path}")
        
        # Clean up old files periodically
        cleanup_old_files()
        
        # Check if cast file exists
        if not os.path.exists(cast_path):
            print(f"[DEBUG] ERROR: Cast file does not exist: {cast_path}")
            with open(progress_path, "w") as pf:
                pf.write(json.dumps({"progress": 0, "done": False, "text": f"Error: Cast file not found: {cast_path}"}))
            return
        
        # Check if file already exists (cache)
        if os.path.exists(mp4_path):
            print(f"[DEBUG] MP4 file already exists: {mp4_path}")
            with open(progress_path, "w") as pf:
                pf.write(json.dumps({"progress": 1.0, "done": True, "text": "File already exists"}))
            return
        
        print(f"[DEBUG] Cast file exists, starting conversion...")
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
        
        # Optimize: Only process output events and skip static frames
        output_events = [evt for evt in events if evt[1] == "o"]
        print(f"[DEBUG] Output events: {len(output_events)}")
        
        last_screen_hash = None
        for i, evt in enumerate(output_events):
            try:
                stream.feed(evt[2])
                
                # Create screen hash to detect changes
                screen_content = str(screen.display)
                current_hash = hash(screen_content)
                
                # Only generate frame if screen changed
                if current_hash != last_screen_hash:
                    # Use Exegol theme colors for exact match with Exegol terminal
                    colors = get_exegol_colors()
                    fg_color = clean_color_for_tty2img(colors['fg'])
                    bg_color = clean_color_for_tty2img(colors['bg'])
                    
                    try:
                        img = tty2img.tty2img(screen, fontSize=font_size, 
                                             fgDefaultColor=fg_color, 
                                             bgDefaultColor=bg_color)
                        img = img.convert("RGB")
                        images.append(np.array(img))
                        timestamps.append(evt[0])
                        last_screen_hash = current_hash
                    except Exception as color_error:
                        print(f"[DEBUG] Color error, using fallback colors: {color_error}")
                        # Fallback to basic colors if there's a color issue
                        img = tty2img.tty2img(screen, fontSize=font_size, 
                                             fgDefaultColor='white', 
                                             bgDefaultColor='black')
                        img = img.convert("RGB")
                        images.append(np.array(img))
                        timestamps.append(evt[0])
                        last_screen_hash = current_hash
                    
                    # Progress update every 5 frames or at the end
                    if len(images) % 5 == 0 or i == len(output_events) - 1:
                        with open(progress_path, "w") as pf:
                            pf.write(json.dumps({
                                "progress": i / len(output_events) if output_events else 1,
                                "done": False,
                                "text": f"Processing frame {len(images)} (t={evt[0]:.1f}s)"
                            }))
                        
            except Exception as e:
                print(f"[!] Frame {i} error: {e}")
        
        print(f"[DEBUG] Generated {len(images)} frames (optimized from {len(output_events)} events)")
        
        if len(timestamps) > 1:
            durations = [s2 - s1 for s1, s2 in zip(timestamps, timestamps[1:])]
            mean_duration = sum(durations) / len(durations)
        else:
            mean_duration = 0.5
            
        with open(progress_path, "w") as pf:
            pf.write(json.dumps({"progress": 1.0, "done": False, "text": "Encoding MP4..."}))
            
        if len(images) > 0:
            fps = 1 / mean_duration if mean_duration > 0 else 2
            # Ensure minimum FPS for compatibility
            fps = max(fps, 5)  # Minimum 5 fps for better compatibility
            # Optimize encoding parameters
            clip = mpy.ImageSequenceClip(images, fps=fps)
            clip.write_videofile(
                mp4_path, 
                codec="libx264", 
                fps=fps, 
                audio=False, 
                logger=None,
                preset="ultrafast",  # Faster encoding
                ffmpeg_params=["-profile:v", "baseline", "-level", "3.0"]  # Better compatibility
            )
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

def cleanup_old_files():
    """Clean up old temporary files to save disk space"""
    temp_dir = tempfile.gettempdir()
    current_time = time.time()
    max_age = 3600  # 1 hour for .cast and .progress files
    max_age_mp4 = 86400  # 24 hours for .mp4 files (keep them longer)
    
    for filename in os.listdir(temp_dir):
        if filename.endswith('.mp4') or filename.endswith('.cast') or filename.endswith('.progress'):
            filepath = os.path.join(temp_dir, filename)
            if os.path.isfile(filepath):
                file_age = current_time - os.path.getmtime(filepath)
                # Use different max age for MP4 files
                max_age_for_file = max_age_mp4 if filename.endswith('.mp4') else max_age
                
                if file_age > max_age_for_file:
                    try:
                        os.remove(filepath)
                        print(f"[DEBUG] Cleaned up old file: {filename}")
                    except Exception as e:
                        print(f"[DEBUG] Failed to clean up {filename}: {e}")

def convert_cast_to_mp4_progress_extract(cast_path, mp4_path, progress_path, start_time, end_time):
    try:
        print(f"[DEBUG] Starting MP4 extract conversion: {cast_path} → {mp4_path} ({start_time:.1f}s to {end_time:.1f}s)")
        
        # Clean up old files periodically
        cleanup_old_files()
        
        # Check if file already exists (cache)
        if os.path.exists(mp4_path):
            print(f"[DEBUG] MP4 extract file already exists: {mp4_path}")
            with open(progress_path, "w") as pf:
                pf.write(json.dumps({"progress": 1.0, "done": True, "text": "File already exists"}))
            return
        
        with open(cast_path) as f:
            lines = f.readlines()
        header = json.loads(lines[0])
        events = [json.loads(l) for l in lines[1:] if l.strip() and l.startswith("[")]
        filtered_events = [e for e in events if start_time <= e[0] <= end_time]
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
        
        # Optimize: Only process output events and skip static frames
        output_events = [evt for evt in filtered_events if evt[1] == "o"]
        print(f"[DEBUG] Output events: {len(output_events)}")
        
        last_screen_hash = None
        for i, evt in enumerate(output_events):
            try:
                stream.feed(evt[2])
                
                # Create screen hash to detect changes
                screen_content = str(screen.display)
                current_hash = hash(screen_content)
                
                # Only generate frame if screen changed
                if current_hash != last_screen_hash:
                    # Use Exegol theme colors for exact match with Exegol terminal
                    colors = get_exegol_colors()
                    fg_color = clean_color_for_tty2img(colors['fg'])
                    bg_color = clean_color_for_tty2img(colors['bg'])
                    
                    try:
                        img = tty2img.tty2img(screen, fontSize=font_size, 
                                             fgDefaultColor=fg_color, 
                                             bgDefaultColor=bg_color)
                        img = img.convert("RGB")
                        images.append(np.array(img))
                        timestamps.append(evt[0])
                        last_screen_hash = current_hash
                    except Exception as color_error:
                        print(f"[DEBUG] Color error, using fallback colors: {color_error}")
                        # Fallback to basic colors if there's a color issue
                        img = tty2img.tty2img(screen, fontSize=font_size, 
                                             fgDefaultColor='white', 
                                             bgDefaultColor='black')
                        img = img.convert("RGB")
                        images.append(np.array(img))
                        timestamps.append(evt[0])
                        last_screen_hash = current_hash
                    
                    # Progress update every 5 frames or at the end
                    if len(images) % 5 == 0 or i == len(output_events) - 1:
                        with open(progress_path, "w") as pf:
                            pf.write(json.dumps({
                                "progress": i / len(output_events) if output_events else 1,
                                "done": False,
                                "text": f"Processing frame {len(images)} (t={evt[0]:.1f}s)"
                            }))
                        
            except Exception as e:
                print(f"[!] Frame {i} error: {e}")
        
        print(f"[DEBUG] Generated {len(images)} frames (optimized from {len(output_events)} events)")
        
        if len(timestamps) > 1:
            durations = [s2 - s1 for s1, s2 in zip(timestamps, timestamps[1:])]
            mean_duration = sum(durations) / len(durations)
        else:
            mean_duration = 0.5
            
        with open(progress_path, "w") as pf:
            pf.write(json.dumps({"progress": 1.0, "done": False, "text": "Encoding MP4..."}))
            
        if len(images) > 0:
            fps = 1 / mean_duration if mean_duration > 0 else 2
            # Ensure minimum FPS for compatibility
            fps = max(fps, 5)  # Minimum 5 fps for better compatibility
            # Optimize encoding parameters
            clip = mpy.ImageSequenceClip(images, fps=fps)
            clip.write_videofile(
                mp4_path, 
                codec="libx264", 
                fps=fps, 
                audio=False, 
                logger=None,
                preset="ultrafast",  # Faster encoding
                ffmpeg_params=["-profile:v", "baseline", "-level", "3.0"]  # Better compatibility
            )
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
