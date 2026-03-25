#!/usr/bin/env python3
"""
Simple OVA Build Manager with Python Backend
Dynamic version column tracking from images.txt
Enhanced with date sorting and validation error focusing
"""

from flask import Flask, render_template_string, jsonify, request
import requests
from bs4 import BeautifulSoup
import re
import subprocess
import os
import paramiko
from flask_socketio import SocketIO, emit
import threading
import json
from markupsafe import Markup 
from datetime import datetime

app = Flask(__name__)
app.config["SECRET_KEY"] = "your-secret-key-here"
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
OVA_BASE_URL = "http://storage1.qnc.kanlab.jnpr.net/ova/"
QPODS = ["q-pod30-vmm", "q-pod32-vmm", "q-pod36-vmm", "q-pod38-vmm"]  # Single source of truth
SSH_DOMAIN = "englab.juniper.net"
SETUP_SCRIPT = "/homes/jtsai/full_setup.sh"
SETUP_PROFILE_BASE = (
    "basicDemo-eop:profile_daily-davinci_eop_dev_release_{version}_vmm_3.0"
)
DEFAULT_PROFILE_VERSION = "2.7.0"

# Store active SSH sessions
active_sessions = {}

# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Launch Setup from OVA Image</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css" />
    <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; }
        .header p { opacity: 0.9; font-size: 1.1em; }
        .content { padding: 30px; }
        .credentials-section {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            border: 2px solid #e9ecef;
        }
        .credentials-section h2 { color: #495057; margin-bottom: 15px; font-size: 1.3em; }
        .input-group {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
        }
        .input-wrapper { display: flex; flex-direction: column; }
        .input-wrapper label {
            margin-bottom: 5px;
            color: #495057;
            font-weight: 600;
            font-size: 0.9em;
        }
        .input-wrapper input {
            padding: 12px;
            border: 2px solid #dee2e6;
            border-radius: 6px;
            font-size: 1em;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #6c757d;
        }
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        /* ── Dynamic table ── */
        .builds-table { width: 100%; border-collapse: collapse; margin-top: 20px; table-layout: auto; }
        .builds-table thead { background: #495057; color: white; position: sticky; top: 0; z-index: 10; }
        .builds-table th { padding: 12px 15px; text-align: left; font-weight: 600; white-space: nowrap; }
        .builds-table th.sortable { cursor: pointer; user-select: none; }
        .builds-table th.sortable:hover { background: #5a6268; }
        .builds-table th .sort-icon { margin-left: 5px; font-size: 0.8em; opacity: 0.5; }
        .builds-table th.sort-active .sort-icon { opacity: 1; }
        .builds-table td { padding: 12px 15px; border-bottom: 1px solid #dee2e6; }
        .builds-table tbody tr:hover { background: #f8f9fa; }

        /* Status column */
        .status-cell { word-wrap: break-word; white-space: normal; vertical-align: top; min-width: 180px; max-width: 320px; }
        .status-progress {
            font-size: 0.7em; color: #495057; background: #f1f3f5;
            padding: 6px 10px; border-radius: 4px; margin-top: 5px;
            font-family: 'Courier New', monospace; max-height: 80px;
            overflow-y: auto; word-wrap: break-word; white-space: pre-wrap;
            border-left: 3px solid #667eea; line-height: 1.4;
        }

        .table-wrapper { max-height: 500px; overflow-y: auto; overflow-x: auto; border: 2px solid #dee2e6; border-radius: 8px; }

        .build-number { font-family: 'Courier New', monospace; color: #495057; font-weight: 600; white-space: nowrap; }
        .version-badge {
            color: #28a745; font-weight: 600; background: #d4edda;
            padding: 4px 8px; border-radius: 4px; display: inline-block;
            font-family: 'Courier New', monospace; font-size: 0.82em;
            white-space: nowrap;
        }
        .version-badge.loading { background: #fff3cd; color: #856404; }
        .version-badge.error { background: #f8d7da; color: #721c24; }
        .version-badge.na { background: #f8f9fa; color: #6c757d; }

        /* Status badges */
        .status-badge {
            padding: 6px 12px; border-radius: 4px; font-weight: 600;
            font-size: 0.85em; display: inline-block; min-width: 90px; text-align: center;
        }
        .status-pending  { background: #fff3cd; color: #856404; border: 1px solid #ffeaa7; }
        .status-deploying { background: #cce5ff; color: #004085; border: 1px solid #b8daff; animation: pulse 2s infinite; }
        .status-success  { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .status-failed   { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .status-stopped  { background: #e2e3e5; color: #383d41; border: 1px solid #d6d8db; }
        .status-none     { background: #f8f9fa; color: #6c757d; border: 1px solid #dee2e6; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.6} }

        /* Column manager */
        .col-manager {
            background: #f8f9fa; padding: 18px 20px; border-radius: 8px;
            border: 2px solid #e9ecef; margin-bottom: 20px;
        }
        .col-manager h2 { color: #495057; margin-bottom: 12px; font-size: 1.15em; }
        .col-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
        .col-tag {
            display: inline-flex; align-items: center; gap: 6px;
            background: white; border: 2px solid #dee2e6; border-radius: 20px;
            padding: 5px 12px; font-size: 0.88em; font-weight: 600; cursor: pointer;
            transition: all 0.2s; user-select: none;
        }
        .col-tag.active { border-color: #667eea; background: #eef0ff; color: #4a5fc1; }
        .col-tag.locked { cursor: default; border-color: #adb5bd; background: #e9ecef; color: #495057; }
        .col-tag .col-remove {
            background: #dc3545; color: white; border: none; border-radius: 50%;
            width: 16px; height: 16px; font-size: 0.75em; cursor: pointer;
            display: flex; align-items: center; justify-content: center; line-height: 1;
        }
        .col-tag.active .col-remove { background: #c82333; }
        .col-add-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        .col-add-row input {
            padding: 8px 12px; border: 2px solid #dee2e6; border-radius: 6px;
            font-size: 0.9em; flex: 1; min-width: 200px;
        }
        .col-add-row select {
            padding: 8px 12px; border: 2px solid #dee2e6; border-radius: 6px;
            font-size: 0.9em; background: white; cursor: pointer;
        }
        .btn-add-col {
            padding: 8px 16px; background: #667eea; color: white; border: none;
            border-radius: 6px; cursor: pointer; font-weight: 600; white-space: nowrap;
        }
        .btn-add-col:hover { background: #5a6fd6; }
        .preset-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
        .preset-chip {
            padding: 4px 10px; background: #e9ecef; border: 1px solid #ced4da;
            border-radius: 12px; font-size: 0.8em; cursor: pointer; color: #495057;
            transition: background 0.15s;
        }
        .preset-chip:hover { background: #d0d7de; }

        /* QPod tag locked badge */
        .qpod-lock-icon { font-size: 0.75em; opacity: 0.6; }

        /* Misc buttons */
        .stop-btn { background: #dc3545; color: white; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 0.85em; margin-left: 5px; }
        .stop-btn:hover { background: #c82333; }
        .create-btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-weight: 600;
        }
        .create-btn:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(102,126,234,0.4); }
        .create-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .alert { 
            padding: 15px 20px; border-radius: 6px; margin-bottom: 20px; display: none;
            scroll-margin-top: 20px;
        }
        .alert.show { display: block; }
        .alert.shake {
            animation: shake 0.5s;
        }
        @keyframes shake {
            0%, 100% { transform: translateX(0); }
            10%, 30%, 50%, 70%, 90% { transform: translateX(-5px); }
            20%, 40%, 60%, 80% { transform: translateX(5px); }
        }
        .alert-success { background: #d4edda; color: #155724; border-left: 4px solid #28a745; }
        .alert-error   { background: #f8d7da; color: #721c24; border-left: 4px solid #dc3545; }
        .alert-info    { background: #d1ecf1; color: #0c5460; border-left: 4px solid #17a2b8; }
        .refresh-btn { background: #28a745; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-weight: 600; margin-bottom: 20px; }
        .capacity-card { background: white; border: 2px solid #dee2e6; border-radius: 6px; padding: 15px; margin-bottom: 10px; transition: border-color 0.3s; }
        .capacity-card:hover { border-color: #667eea; }
        .capacity-card.success { border-left: 4px solid #28a745; }
        .capacity-card.error   { border-left: 4px solid #dc3545; }
        .capacity-header { font-weight: 600; color: #495057; font-size: 1.1em; margin-bottom: 8px; }
        .capacity-memory { color: #28a745; font-family: 'Courier New', monospace; background: #f8f9fa; padding: 8px; border-radius: 4px; margin-top: 5px; }
        .capacity-error  { color: #dc3545; font-size: 0.9em; }
        .terminal-container { background: #1e1e1e; border-radius: 8px; padding: 20px; margin-top: 20px; display: none; }
        .terminal-header {
            background: #2d2d2d; padding: 10px 15px; border-radius: 6px 6px 0 0;
            margin: -20px -20px 10px -20px; color: #fff; font-weight: 600;
            display: flex; justify-content: space-between; align-items: center;
        }
        .terminal-controls button { background: #dc3545; color: white; border: none; padding: 5px 15px; border-radius: 4px; cursor: pointer; font-size: 0.9em; }
        .terminal-controls button:hover { background: #c82333; }
        .info-note { background: #e7f3ff; border-left: 4px solid #2196F3; padding: 15px; margin: 20px 0; border-radius: 4px; color: #0c5460; }
        .info-note strong { color: #1976D2; }
        .footer { text-align: center; padding: 20px; color: #6c757d; font-size: 0.9em; border-top: 2px solid #e9ecef; margin-top: 30px; }

        /* QPod count badge */
        .qpod-count {
            display: inline-flex; align-items: center; justify-content: center;
            background: #667eea; color: white; border-radius: 10px;
            padding: 2px 8px; font-size: 0.75em; font-weight: 700; margin-left: 8px;
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🚀 Launch Setup from OVA Image</h1>
        <p>Automated Build Deployment System</p>
    </div>
    <div class="content">

        <!-- Credentials -->
        <div class="credentials-section">
            <h2>SSH Credentials</h2>
            <div class="input-group">
                <div class="input-wrapper">
                    <label for="unix-id">Unix ID:</label>
                    <input type="text" id="unix-id" placeholder="Enter your Unix ID">
                </div>
                <div class="input-wrapper">
                    <label for="password">Password:</label>
                    <div style="position:relative;width:100%;display:block;">
                        <input type="password" id="password" placeholder="Enter your password" style="width:100%;padding:12px 45px 12px 12px;border:2px solid #dee2e6;border-radius:6px;font-size:1em;box-sizing:border-box;">
                        <button type="button" onclick="togglePassword()" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:transparent;border:none;cursor:pointer;font-size:1.1em;padding:0;line-height:1;">
                            <span id="password-toggle-icon">👁️</span>
                        </button>
                    </div>
                </div>
            </div>
            <div style="margin-top:15px;display:flex;gap:10px;flex-wrap:wrap;">
                <button class="refresh-btn" style="margin-bottom:0;" onclick="checkCapacities()">🔍 Check QPod Capacities</button>
                <button class="refresh-btn" style="margin-bottom:0;background:#28a745;" onclick="openBlankTerminal()">💻 Just Open Terminal</button>
            </div>
        </div>
        <div class="alert" id="alert"></div>
        <!-- QPod Capacity -->
        <div id="capacity-section" style="margin-bottom:30px;">
            <div class="credentials-section">
                <h2>
                    🖥️ QPod Manager
                    <span class="qpod-count" id="qpod-count">0</span>
                </h2>

                <!-- QPod Tags -->
                <div style="margin-bottom:6px;color:#6c757d;font-size:0.85em;">
                    🔒 Default QPods are locked &nbsp;·&nbsp; Custom QPods can be removed
                </div>
                <div class="col-tags" id="qpod-tags" style="margin-bottom:14px;min-height:36px;"></div>

                <!-- Add Custom QPod -->
                <div class="col-add-row" style="margin-bottom:20px;">
                    <input type="text" id="custom-qpod" placeholder="Add custom QPod (e.g., q-pod40-vmm)" style="flex:1;min-width:220px;">
                    <button class="btn-add-col" onclick="addCustomQpod()">+ Add QPod</button>
                </div>

                <!-- Divider -->
                <hr style="border:none;border-top:2px solid #e9ecef;margin-bottom:18px;">

                <!-- Capacity Results -->
                <div id="capacity-loading" class="loading" style="display:none;padding:20px;">
                    <div class="spinner"></div><p>Checking QPod capacities...</p>
                </div>
                <div id="capacity-results"></div>

                <!-- QPod Selector -->
                <div id="qpod-selector-section" style="display:none;margin-top:15px;">
                    <label style="font-weight:600;color:#495057;margin-bottom:10px;display:block;">Select QPod for Deployment:</label>
                    <select id="qpod-select" style="width:100%;padding:12px;border:2px solid #dee2e6;border-radius:6px;font-size:1em;">
                        <option value="">Choose a QPod...</option>
                    </select>
                    <button class="refresh-btn" onclick="connectToQpod()" style="margin-top:10px;background:#17a2b8;">
                        🔌 Connect to QPod (SSH Only)
                    </button>
                </div>

                <div class="info-note" style="margin-top:15px;">
                    <strong>📝 Note:</strong> To view the UI IP address after deployment, run:
                    <code style="background:#fff;padding:2px 6px;border-radius:3px;color:#d63384;">vmm ip -a</code>
                </div>
            </div>
        </div>


        <!-- Profile Release Version -->
        <div class="col-manager" style="margin-bottom:20px;">
            <h2>Profile Release Version <small style="font-weight:400;color:#6c757d;font-size:0.85em;">select or add a release version for deployment</small></h2>
            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px;">
                <select id="profile-version" style="flex:1;min-width:220px;padding:11px 12px;border:2px solid #dee2e6;border-radius:6px;font-size:1em;background:white;"></select>
            </div>
            <div class="col-add-row">
                <input type="text" id="new-profile-version" placeholder="Add version, e.g. 3.1.0">
                <button class="btn-add-col" onclick="addProfileVersion()">+ Add Version</button>
            </div>
            <div id="profile-version-tags" class="col-tags" style="margin-top:10px;"></div>
        </div>

        <!-- Version Column Manager -->
        <div class="col-manager">
            <h2>📦 Version Columns <small style="font-weight:400;color:#6c757d;font-size:0.85em;">— choose which image versions to show in the table</small></h2>

            <div style="margin-bottom:8px;color:#6c757d;font-size:0.85em;">Quick add:</div>
            <div class="preset-chips" id="preset-chips">
                <!-- filled by JS -->
            </div>

            <div class="col-tags" id="col-tags"><!-- filled by JS --></div>

            <div class="col-add-row">
                <input type="text" id="new-col-key" placeholder="Image key, e.g. papi  or  mistsys/alert-manager">
                <input type="text" id="new-col-label" placeholder="Display label (optional)">
                <button class="btn-add-col" onclick="addColumn()">+ Add Column</button>
            </div>
        </div>

        <button class="refresh-btn" onclick="loadBuilds()">🔄 Refresh Builds</button>

        <!-- Search -->
        <div style="margin-bottom:15px;">
            <input type="text" id="build-search" placeholder="🔍 Search builds by name or date..."
                   oninput="filterBuilds()"
                   style="width:100%;padding:12px;border:2px solid #dee2e6;border-radius:6px;font-size:1em;box-sizing:border-box;">
            <div id="search-results" style="margin-top:8px;color:#6c757d;font-size:0.9em;"></div>
        </div>

        <div class="loading" id="loading">
            <div class="spinner"></div><p>Loading available builds...</p>
        </div>

        <div id="builds-container" style="display:none;">
            <div class="table-wrapper">
                <table class="builds-table">
                    <thead><tr id="table-head-row"></tr></thead>
                    <tbody id="builds-tbody"></tbody>
                </table>
            </div>
        </div>

        <!-- Terminals Container -->
        <div id="terminals-container" style="margin-top:20px;"></div>

        <div class="footer">© HPE {{ current_year }} - All Rights Reserved</div>
    </div>
</div>

<script>
const SSH_DOMAIN = '{{ ssh_domain }}';
const SETUP_SCRIPT = '{{ setup_script }}';

// ── Single source of truth: injected from Python QPODS ───────────────────────
const DEFAULT_QPODS = {{ qpods_json }};

let builds = [];
let customQpods = [];   // user-added QPods (persisted in localStorage)
let buildStatuses = {};
let activeDeployments = {};
let terminals = [];
let terminalSockets = [];
let currentSort = { column: 'date', direction: 'desc' }; // Default sort

// ── QPod management ───────────────────────────────────────────────────────────
function loadQpods() {
    const stored = localStorage.getItem('customQpods');
    if (stored) {
        try {
            const parsed = JSON.parse(stored);
            parsed.forEach(q => {
                if (!customQpods.includes(q) && !DEFAULT_QPODS.includes(q)) {
                    customQpods.push(q);
                }
            });
        } catch(e) {}
    }
    renderQpodTags();
}

function saveCustomQpods() {
    localStorage.setItem('customQpods', JSON.stringify(customQpods));
}

function getAllQpods() {
    return [...DEFAULT_QPODS, ...customQpods];
}

function renderQpodTags() {
    const container = document.getElementById('qpod-tags');
    if (!container) return;
    container.innerHTML = '';

    // Default QPods — locked, no remove button
    DEFAULT_QPODS.forEach(q => {
        const tag = document.createElement('div');
        tag.className = 'col-tag active locked';
        tag.title = q + '.' + SSH_DOMAIN + ' (default — cannot be removed)';
        tag.innerHTML = '<span class="qpod-lock-icon">🔒</span> ' + escapeHtml(q);
        container.appendChild(tag);
    });

    // Custom QPods — removable
    customQpods.forEach((q, i) => {
        const tag = document.createElement('div');
        tag.className = 'col-tag active';
        tag.title = q + '.' + SSH_DOMAIN;
        tag.innerHTML =
            escapeHtml(q) +
            ` <button class="col-remove" title="Remove QPod" onclick="removeCustomQpod(${i})">×</button>`;
        container.appendChild(tag);
    });

    // Update count badge
    const countEl = document.getElementById('qpod-count');
    if (countEl) countEl.textContent = getAllQpods().length;
}

function addCustomQpod() {
    const input = document.getElementById('custom-qpod');
    const qpod = input.value.trim();
    if (!qpod) { showAlert('Please enter a QPod name', 'error'); return; }
    if (!qpod.includes('vmm')) { showAlert('QPod name should contain "vmm"', 'error'); return; }
    if (getAllQpods().includes(qpod)) { showAlert('QPod already exists', 'error'); return; }
    customQpods.push(qpod);
    saveCustomQpods();
    renderQpodTags();
    input.value = '';
    showAlert('QPod added: ' + qpod, 'success');
}

function removeCustomQpod(i) {
    if (!confirm('Remove QPod "' + customQpods[i] + '"?')) return;
    customQpods.splice(i, 1);
    saveCustomQpods();
    renderQpodTags();
    // Remove from dropdown if it was selected
    const sel = document.getElementById('qpod-select');
    const current = sel.value;
    Array.from(sel.options).forEach(opt => {
        if (!getAllQpods().includes(opt.value) && opt.value !== '') {
            sel.removeChild(opt);
        }
    });
    showAlert('QPod removed', 'info');
}

// ── Column config ────────────────────────────────────────────────────────────
const PRESETS = [
    { key: 'epic-ui',         label: 'EPIC UI' },
    { key: 'papi',            label: 'PAPI' },
    { key: 'alert-manager',   label: 'Alert Manager' },
    { key: 'agatha',          label: 'Agatha' },
    { key: 'paa/orchestrator',label: 'Orchestrator' },
    { key: 'northstar-docker-local/common-utils', label: 'Common Utils' },
];

let trackedCols = [];
let versionCache = {};

function loadColConfig() {
    const stored = localStorage.getItem('trackedCols_v2');
    if (stored) {
        try { trackedCols = JSON.parse(stored); return; } catch(e) {}
    }
    trackedCols = [{ key: 'epic-ui', label: 'EPIC UI', visible: true }];
}

function saveColConfig() {
    localStorage.setItem('trackedCols_v2', JSON.stringify(trackedCols));
}

function renderPresetChips() {
    const container = document.getElementById('preset-chips');
    container.innerHTML = '';
    PRESETS.forEach(p => {
        const already = trackedCols.find(c => c.key === p.key);
        if (already) return;
        const chip = document.createElement('span');
        chip.className = 'preset-chip';
        chip.textContent = '+ ' + p.label;
        chip.onclick = () => addColumnRaw(p.key, p.label);
        container.appendChild(chip);
    });
}

function renderColTags() {
    const container = document.getElementById('col-tags');
    container.innerHTML = '';
    trackedCols.forEach((col, i) => {
        const tag = document.createElement('div');
        tag.className = 'col-tag' + (col.visible ? ' active' : '');
        tag.title = col.key;
        tag.onclick = (e) => {
            if (e.target.classList.contains('col-remove')) return;
            trackedCols[i].visible = !trackedCols[i].visible;
            saveColConfig();
            renderColTags();
            if (builds.length) renderBuilds();
        };
        tag.innerHTML =
            (col.visible ? '👁 ' : '🚫 ') + escapeHtml(col.label) +
            ` <button class="col-remove" title="Remove column" onclick="removeColumn(${i})">×</button>`;
        container.appendChild(tag);
    });
    renderPresetChips();
}

function addColumnRaw(key, label) {
    key = key.trim();
    label = (label || '').trim() || key;
    if (!key) { showAlert('Enter an image key', 'error'); return; }
    if (trackedCols.find(c => c.key === key)) { showAlert('Column already exists', 'error'); return; }
    trackedCols.push({ key, label, visible: true });
    saveColConfig();
    renderColTags();
    if (builds.length) {
        renderBuilds();
        fetchVersionsForColumn(key);
    }
    document.getElementById('new-col-key').value = '';
    document.getElementById('new-col-label').value = '';
}

function addColumn() {
    const key   = document.getElementById('new-col-key').value.trim();
    const label = document.getElementById('new-col-label').value.trim();
    addColumnRaw(key, label || key);
}

function removeColumn(i) {
    if (!confirm('Remove column "' + trackedCols[i].label + '"?')) return;
    trackedCols.splice(i, 1);
    saveColConfig();
    renderColTags();
    if (builds.length) renderBuilds();
}

// ── Status helpers ────────────────────────────────────────────────────────────
function loadBuildStatuses() {
    const s = localStorage.getItem('buildStatuses');
    if (s) { try { buildStatuses = JSON.parse(s); } catch(e) { buildStatuses = {}; } }
}
function saveBuildStatuses() { localStorage.setItem('buildStatuses', JSON.stringify(buildStatuses)); }
function getBuildStatus(n) { return buildStatuses[n] || { status:'none', timestamp:null, qpod:null, progress:'' }; }
function setBuildStatus(buildName, status, qpod, progress) {
    buildStatuses[buildName] = {
        status, qpod: qpod || buildStatuses[buildName]?.qpod,
        timestamp: new Date().toISOString(),
        progress: progress !== undefined ? progress : (buildStatuses[buildName]?.progress || '')
    };
    saveBuildStatuses();
    updateBuildStatusDisplay(buildName);
}
function updateBuildStatusDisplay(buildName) {
    const row = document.querySelector('[data-build-name="' + buildName.toLowerCase() + '"]');
    if (row) {
        const cell = row.querySelector('.status-cell');
        if (cell) cell.innerHTML = getStatusHTML(buildName);
    }
}
function escapeHtml(t) {
    const d = document.createElement('div'); d.textContent = t; return d.innerHTML;
}
function getStatusHTML(buildName) {
    const si = getBuildStatus(buildName);
    const status = si.status, progress = si.progress || '';
    let badge = '', stopBtn = '', progressDiv = '';
    switch(status) {
        case 'pending':   badge = '<span class="status-badge status-pending">⏳ Started</span>'; break;
        case 'deploying':
            badge = '<span class="status-badge status-deploying">🚀 Deploying</span>';
            stopBtn = '<button class="stop-btn" onclick="stopDeployment(\\\'' + buildName + '\\\')">Stop</button>';
            if (progress) progressDiv = '<div class="status-progress">' + escapeHtml(progress) + '</div>';
            break;
        case 'success': badge = '<span class="status-badge status-success">✅ Success</span>'; break;
        case 'failed':  badge = '<span class="status-badge status-failed">❌ Failed</span>'; break;
        case 'stopped': badge = '<span class="status-badge status-stopped">⏹️ Stopped</span>'; break;
        default:        badge = '<span class="status-badge status-none">Not Started</span>';
    }
    return '<div>' + badge + stopBtn + progressDiv + '</div>';
}

function stopDeployment(buildName) {
    if (!confirm('Stop monitoring for ' + buildName + '?')) return;
    setBuildStatus(buildName, 'stopped', null);
    if (activeDeployments[buildName]) {
        activeDeployments[buildName].emit('stop_monitoring');
        activeDeployments[buildName].disconnect();
        delete activeDeployments[buildName];
    }
    showAlert('Monitoring stopped for ' + buildName, 'info');
}

// ── Sorting functionality ─────────────────────────────────────────────────────
function parseDate(dateStr) {
    if (!dateStr || dateStr === 'N/A') return null;
    try {
        // Parse format: "02-Mar-2024 12:34"
        const parts = dateStr.split(' ');
        const datePart = parts[0].split('-');
        const timePart = parts[1] ? parts[1].split(':') : ['00', '00'];
        
        const monthMap = {
            'Jan': 0, 'Feb': 1, 'Mar': 2, 'Apr': 3, 'May': 4, 'Jun': 5,
            'Jul': 6, 'Aug': 7, 'Sep': 8, 'Oct': 9, 'Nov': 10, 'Dec': 11
        };
        
        const day = parseInt(datePart[0]);
        const month = monthMap[datePart[1]];
        const year = parseInt(datePart[2]);
        const hour = parseInt(timePart[0]);
        const minute = parseInt(timePart[1]);
        
        return new Date(year, month, day, hour, minute);
    } catch(e) {
        return null;
    }
}

function sortBuilds(column) {
    // Toggle direction if same column, else default to desc
    if (currentSort.column === column) {
        currentSort.direction = currentSort.direction === 'desc' ? 'asc' : 'desc';
    } else {
        currentSort.column = column;
        currentSort.direction = column === 'date' ? 'desc' : 'asc'; // dates default to newest first
    }
    
    builds.sort((a, b) => {
        let valA, valB;
        
        if (column === 'name') {
            valA = a.name.toLowerCase();
            valB = b.name.toLowerCase();
        } else if (column === 'date') {
            valA = parseDate(a.date);
            valB = parseDate(b.date);
            
            // Handle null dates
            if (!valA && !valB) return 0;
            if (!valA) return 1;
            if (!valB) return -1;
        }
        
        let result;
        if (valA < valB) result = -1;
        else if (valA > valB) result = 1;
        else result = 0;
        
        return currentSort.direction === 'desc' ? -result : result;
    });
    
    renderBuilds();
}

// ── Table rendering ───────────────────────────────────────────────────────────
function renderBuilds() {
    var visibleCols = trackedCols.filter(function(c) { return c.visible; });

    var headRow = document.getElementById('table-head-row');
    headRow.innerHTML = '';

    var buildSortIcon = currentSort.column === 'name' ? (currentSort.direction === 'desc' ? '▼' : '▲') : '⇅';
    var dateSortIcon  = currentSort.column === 'date' ? (currentSort.direction === 'desc' ? '▼' : '▲') : '⇅';

    function makeHeaderCell(label, colKey, sortIcon) {
        var th = document.createElement('th');
        th.className = 'sortable' + (currentSort.column === colKey ? ' sort-active' : '');
        th.innerHTML = label + ' <span class="sort-icon">' + sortIcon + '</span>';
        th.onclick = function() { sortBuilds(colKey); };
        return th;
    }

    headRow.appendChild(makeHeaderCell('Build Number', 'name', buildSortIcon));
    headRow.appendChild(makeHeaderCell('Date', 'date', dateSortIcon));
    visibleCols.forEach(function(c) {
        var th = document.createElement('th');
        th.textContent = c.label;
        headRow.appendChild(th);
    });
    var thStatus = document.createElement('th');
    thStatus.innerHTML = 'Status &amp; Progress';
    headRow.appendChild(thStatus);
    var thAction = document.createElement('th');
    thAction.textContent = 'Action';
    headRow.appendChild(thAction);

    var tbody = document.getElementById('builds-tbody');
    tbody.innerHTML = '';

    builds.forEach(function(build, index) {
        var row = document.createElement('tr');
        row.className = 'build-row';
        row.id = 'build-row-' + index;
        row.setAttribute('data-build-name', build.name.toLowerCase());
        row.setAttribute('data-build-date', (build.date || '').toLowerCase());

        var tdName = document.createElement('td');
        tdName.className = 'build-number';
        tdName.textContent = build.name;
        row.appendChild(tdName);

        var tdDate = document.createElement('td');
        tdDate.style.cssText = 'color:#6c757d;white-space:nowrap;';
        tdDate.textContent = build.date || 'N/A';
        row.appendChild(tdDate);

        visibleCols.forEach(function(col) {
            var cached = (versionCache[build.name] || {})[col.key];
            var td = document.createElement('td');
            var span = document.createElement('span');
            span.id = 'ver-' + index + '-' + sanitizeId(col.key);
            span.className = 'version-badge';
            if (!cached) {
                span.className += ' loading';
                span.textContent = 'Loading...';
            } else if (cached === 'Error') {
                span.className += ' error';
                span.textContent = cached;
            } else if (cached === 'N/A') {
                span.className += ' na';
                span.textContent = cached;
            } else {
                span.textContent = cached;
            }
            td.appendChild(span);
            row.appendChild(td);
        });

        var tdStatus = document.createElement('td');
        tdStatus.className = 'status-cell';
        tdStatus.innerHTML = getStatusHTML(build.name);
        row.appendChild(tdStatus);

        var tdAction = document.createElement('td');
        var btn = document.createElement('button');
        btn.className = 'create-btn';
        btn.textContent = 'Create Setup';
        btn.onclick = (function(i) { return function() { createBuild(i); }; })(index);
        tdAction.appendChild(btn);
        row.appendChild(tdAction);

        tbody.appendChild(row);
    });
}

function sanitizeId(key) {
    return key.replace(/[^a-zA-Z0-9]/g, '_');
}

function updateVersionCell(index, colKey, version) {
    const cellId = 'ver-' + index + '-' + sanitizeId(colKey);
    const cell = document.getElementById(cellId);
    if (!cell) return;
    cell.textContent = version;
    cell.className = 'version-badge';
    if (!version || version === 'Loading...') { cell.className += ' loading'; }
    else if (version === 'Error') { cell.className += ' error'; }
    else if (version === 'N/A')   { cell.className += ' na'; }
}

// ── Version fetching ──────────────────────────────────────────────────────────
async function fetchVersionsForColumn(colKey) {
    const batchSize = 5;
    for (let i = 0; i < builds.length; i += batchSize) {
        const batch = builds.slice(i, i + batchSize);
        await Promise.all(batch.map(async (build, bi) => {
            const globalIndex = i + bi;
            try {
                const r = await fetch('/api/image-version/' + encodeURIComponent(build.name) + '?image=' + encodeURIComponent(colKey));
                const d = await r.json();
                if (!versionCache[build.name]) versionCache[build.name] = {};
                versionCache[build.name][colKey] = d.version;
                updateVersionCell(globalIndex, colKey, d.version);
            } catch(e) {
                updateVersionCell(globalIndex, colKey, 'Error');
            }
        }));
    }
}

async function fetchAllVersions() {
    const visible = trackedCols.filter(c => c.visible);
    await Promise.all(visible.map(col => fetchVersionsForColumn(col.key)));
    showAlert('All versions loaded!', 'success');
}

// ── Load builds ───────────────────────────────────────────────────────────────
async function loadBuilds() {
    const loading = document.getElementById('loading');
    const container = document.getElementById('builds-container');
    loading.style.display = 'block';
    container.style.display = 'none';
    versionCache = {};
    hideAlert();

    try {
        const r = await fetch('/api/builds');
        builds = await r.json();
        loading.style.display = 'none';
        if (builds.error) { showAlert('Error: ' + builds.error, 'error'); return; }
        if (!builds.length) { showAlert('No builds found', 'error'); return; }
        
        // Builds are already sorted by date (newest first) from backend
        currentSort = { column: 'date', direction: 'desc' };
        
        renderBuilds();
        container.style.display = 'block';
        showAlert('Loaded ' + builds.length + ' builds! Fetching versions...', 'info');
        fetchAllVersions();
    } catch(e) {
        loading.style.display = 'none';
        showAlert('Failed to load builds: ' + e.message, 'error');
    }
}

function filterBuilds() {
    const filter = document.getElementById('build-search').value.toLowerCase();
    const rows = document.querySelectorAll('.build-row');
    let visible = 0;
    rows.forEach(row => {
        const match = row.getAttribute('data-build-name').includes(filter) ||
                      row.getAttribute('data-build-date').includes(filter);
        row.style.display = match ? '' : 'none';
        if (match) visible++;
    });
    const sr = document.getElementById('search-results');
    if (filter) { sr.textContent = 'Showing ' + visible + ' of ' + builds.length + ' builds'; }
    else { sr.textContent = ''; }
}

// ── Build creation ────────────────────────────────────────────────────────────
function createBuild(index) {
    const unixId   = document.getElementById('unix-id').value.trim();
    const password = document.getElementById('password').value;
    const qpod     = document.getElementById('qpod-select').value;
    if (!unixId || !password) { showAlert('Please enter Unix ID and Password', 'error'); return; }
    if (!qpod) { showAlert('Please check capacities and select a QPod first', 'error'); return; }
    executeInTerminal(unixId, password, qpod, builds[index].name);
}

// ── Terminal helpers ──────────────────────────────────────────────────────────
function togglePassword() {
    const i = document.getElementById('password');
    const ico = document.getElementById('password-toggle-icon');
    i.type = i.type === 'password' ? 'text' : 'password';
    ico.textContent = i.type === 'password' ? '👁️' : '🙈';
}

function makeTerminal(terminalId, titleHtml) {
    const terminalsContainer = document.getElementById('terminals-container');
    const terminalContainer = document.createElement('div');
    terminalContainer.className = 'terminal-container';
    terminalContainer.id = terminalId + '-container';
    terminalContainer.style.cssText = 'margin-bottom:20px;display:block;';
    terminalContainer.innerHTML =
        '<div class="terminal-header">' +
            '<span>' + titleHtml + '</span>' +
            '<div class="terminal-controls">' +
                '<button onclick="sendCtrlCToTerminal(\\\'' + terminalId + '\\\')" style="background:#ffc107;margin-right:10px;color:#000;">Ctrl+C</button>' +
                '<button onclick="closeTerminal(\\\'' + terminalId + '\\\')">Close</button>' +
            '</div>' +
        '</div>' +
        '<div id="' + terminalId + '"></div>';
    terminalsContainer.appendChild(terminalContainer);

    const term = new Terminal({
        cursorBlink: true, fontSize: 14,
        fontFamily: 'Menlo, Monaco, "Courier New", monospace',
        theme: {
            background:'#1e1e1e', foreground:'#f0f0f0', cursor:'#f0f0f0',
            selection:'rgba(255,255,255,0.3)', black:'#000000', red:'#e74856',
            green:'#16c60c', yellow:'#f9f1a5', blue:'#3b78ff',
            magenta:'#b4009e', cyan:'#61d6d6', white:'#f0f0f0'
        }
    });
    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(document.getElementById(terminalId));
    fitAddon.fit();
    term.focus();
    terminalContainer.scrollIntoView({ behavior: 'smooth' });
    terminals.push({ id: terminalId, term, fitAddon });
    return { term, fitAddon };
}

function openBlankTerminal() {
    const terminalId = 'terminal-' + Date.now();
    const { term } = makeTerminal(terminalId, '💻 Interactive Terminal');
    term.writeln('\\x1b[1;36m💻 Interactive Terminal\\x1b[0m');
    term.writeln('\\x1b[90m' + '='.repeat(60) + '\\x1b[0m');
    term.writeln('\\x1b[1;33mType any command and press Enter.\\x1b[0m');
    term.writeln('  \\x1b[32mssh user@q-pod30-vmm.englab.juniper.net\\x1b[0m');
    term.writeln('\\x1b[90m' + '='.repeat(60) + '\\x1b[0m');
    term.writeln('');
    term.write('$ ');

    const socket = io();
    terminalSockets.push({ id: terminalId, socket });

    let commandBuffer = '', isExecuting = false;

    socket.on('output', msg => { term.write(msg.data); });
    socket.on('command_ended', () => { isExecuting = false; term.write('\\r\\n$ '); commandBuffer = ''; });
    socket.on('error', msg => {
        term.writeln('\\r\\n\\x1b[1;31mError: ' + msg.error + '\\x1b[0m\\r\\n');
        isExecuting = false; term.write('$ '); commandBuffer = '';
    });

    term.onData(data => {
        if (isExecuting) { socket.emit('input', { data }); return; }
        const code = data.charCodeAt(0);
        if (data === '\\r' || data === '\\n') {
            term.write('\\r\\n');
            if (commandBuffer.trim()) { isExecuting = true; socket.emit('execute_command', { command: commandBuffer.trim() }); }
            else { term.write('$ '); }
            commandBuffer = '';
        } else if (code === 127 || code === 8) {
            if (commandBuffer.length > 0) { commandBuffer = commandBuffer.slice(0,-1); term.write('\\b \\b'); }
        } else if (code === 3) {
            if (isExecuting) socket.emit('kill_session');
            term.write('^C\\r\\n$ '); commandBuffer = ''; isExecuting = false;
        } else if (code >= 32 && code < 127) { commandBuffer += data; term.write(data); }
    });

    showAlert('Interactive terminal opened!', 'success');
}

function connectToQpod() {
    const unixId   = document.getElementById('unix-id').value.trim();
    const password = document.getElementById('password').value;
    const qpod     = document.getElementById('qpod-select').value;
    if (!unixId || !password) { showAlert('Please enter Unix ID and Password', 'error'); return; }
    if (!qpod) { showAlert('Please select a QPod first', 'error'); return; }
    openTerminalForSSH(unixId, password, qpod);
}

function openTerminalForSSH(unixId, password, qpod) {
    const terminalId = 'terminal-' + Date.now();
    const { term } = makeTerminal(terminalId, '🔌 SSH - ' + qpod);
    term.writeln('\\x1b[1;36m🔌 SSH Connection\\x1b[0m');
    term.writeln('\\x1b[90m' + '='.repeat(60) + '\\x1b[0m');
    term.writeln('\\x1b[1;33mQPod:\\x1b[0m ' + qpod + '.' + SSH_DOMAIN);
    term.writeln('');

    const socket = io();
    terminalSockets.push({ id: terminalId, socket });
    term.onData(data => socket.emit('input', { data }));
    socket.on('output', msg => { term.write(msg.data); });
    socket.on('error', msg => { term.writeln('\\r\\n\\x1b[1;31m' + msg.error + '\\x1b[0m\\r\\n'); showAlert('Error: ' + msg.error, 'error'); });
    socket.on('session_ended', () => { term.writeln('\\r\\n\\x1b[1;32m✓ Session ended\\x1b[0m\\r\\n'); });
    socket.emit('connect_ssh', { unix_id: unixId, password, qpod });
}

function executeInTerminal(unixId, password, qpod, buildName) {
    const terminalId = 'terminal-' + Date.now();
    setBuildStatus(buildName, 'pending', qpod);

    const { term } = makeTerminal(terminalId, '🖥️ ' + buildName + ' @ ' + qpod);
    term.writeln('\\x1b[1;36m🚀 OVA Image Tool\\x1b[0m');
    term.writeln('\\x1b[90m' + '='.repeat(60) + '\\x1b[0m');
    term.writeln('\\x1b[1;33mQPod:\\x1b[0m ' + qpod + '.' + SSH_DOMAIN);
    term.writeln('\\x1b[1;33mBuild:\\x1b[0m ' + buildName);
    term.writeln('\\x1b[90m' + '='.repeat(60) + '\\x1b[0m');
    term.writeln('\\x1b[1;32m✓ Terminal ready\\x1b[0m');
    term.writeln('');

    const socket = io();
    terminalSockets.push({ id: terminalId, socket });
    term.onData(data => socket.emit('input', { data }));
    socket.on('output', msg => {
        term.write(msg.data);
        if (msg.data.includes('Please check the progress by tail')) setBuildStatus(buildName, 'deploying', qpod);
    });
    socket.on('error', msg => {
        term.writeln('\\r\\n\\x1b[1;31mError: ' + msg.error + '\\x1b[0m\\r\\n');
        showAlert('Error: ' + msg.error, 'error');
        setBuildStatus(buildName, 'failed', qpod, '');
    });
    socket.on('session_ended', () => {
        term.writeln('\\r\\n\\x1b[1;32m✓ Setup script completed\\x1b[0m\\r\\n');
        term.writeln('\\x1b[1;33m📋 Monitoring logs automatically...\\x1b[0m\\r\\n');
        setBuildStatus(buildName, 'deploying', qpod);

        const qpodNumber = qpod.match(/q-pod(\\d+)/)?.[1] || '30';
        const logPath = '~/ns_launcher_data/q-pod' + qpodNumber + '/progress.log';
        term.writeln('\\r\\n\\x1b[1;36mℹ️  Auto-monitoring: ' + logPath + '\\x1b[0m\\r\\n');

        const monitorSocket = io();
        activeDeployments[buildName] = monitorSocket;

        monitorSocket.on('log_progress', data => {
            if (data.build_name === buildName) setBuildStatus(buildName, 'deploying', qpod, data.log_snippet);
        });
        monitorSocket.on('deployment_status', data => {
            if (data.build_name !== buildName) return;
            if (data.status === 'success') {
                setBuildStatus(buildName, 'success', qpod, '');
                term.writeln('\\r\\n\\x1b[1;32m✅ DEPLOYMENT SUCCESSFUL!\\x1b[0m\\r\\n');
                showAlert('✅ Deployment successful for ' + buildName, 'success');
            } else if (data.status === 'failed') {
                setBuildStatus(buildName, 'failed', qpod, '');
                term.writeln('\\r\\n\\x1b[1;31m❌ DEPLOYMENT FAILED\\x1b[0m\\r\\n');
                showAlert('❌ Deployment failed for ' + buildName, 'error');
            } else if (data.status === 'timeout') {
                setBuildStatus(buildName, 'failed', qpod, '');
                term.writeln('\\r\\n\\x1b[1;33m⏱️ DEPLOYMENT TIMEOUT\\x1b[0m\\r\\n');
                showAlert('⏱️ Timeout for ' + buildName, 'error');
            }
            monitorSocket.disconnect();
            delete activeDeployments[buildName];
        });
        monitorSocket.emit('monitor_deployment', { unix_id: unixId, password, qpod, build_name: buildName, log_path: logPath });
        showAlert('Build deployment started for ' + buildName, 'info');
    });

    socket.emit('start_session', { unix_id: unixId, password, qpod, build_name: buildName });
}

function sendCtrlCToTerminal(terminalId) {
    const s = terminalSockets.find(x => x.id === terminalId);
    if (s) { s.socket.emit('kill_session'); showAlert('Sent Ctrl+C', 'info'); }
}

function closeTerminal(terminalId) {
    const c = document.getElementById(terminalId + '-container');
    if (c) c.remove();
    const si = terminalSockets.findIndex(x => x.id === terminalId);
    if (si !== -1) { terminalSockets[si].socket.disconnect(); terminalSockets.splice(si,1); }
    const ti = terminals.findIndex(x => x.id === terminalId);
    if (ti !== -1) { terminals[ti].term.dispose(); terminals.splice(ti,1); }
}

// ── Check QPod capacities ─────────────────────────────────────────────────────
async function checkCapacities() {
    const unixId   = document.getElementById('unix-id').value.trim();
    const password = document.getElementById('password').value;
    if (!unixId || !password) { showAlert('Please enter Unix ID and Password first', 'error'); return; }

    const loading  = document.getElementById('capacity-loading');
    const results  = document.getElementById('capacity-results');
    const sel      = document.getElementById('qpod-select');
    const selectorSection = document.getElementById('qpod-selector-section');

    loading.style.display = 'block';
    results.innerHTML = '';
    sel.innerHTML = '<option value="">Choose a QPod...</option>';
    selectorSection.style.display = 'none';
    hideAlert();

    try {
        const r = await fetch('/api/check-capacity', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ unix_id: unixId, password, custom_qpods: customQpods })
        });
        const capacities = await r.json();
        loading.style.display = 'none';
        if (capacities.error) { showAlert('Error: ' + capacities.error, 'error'); return; }

        let hasSuccess = false;
        capacities.forEach(cap => {
            const card = document.createElement('div');
            card.className = 'capacity-card ' + cap.status;
            if (cap.status === 'success') {
                hasSuccess = true;
                card.innerHTML =
                    '<div class="capacity-header">📊 ' + escapeHtml(cap.qpod) + '</div>' +
                    '<div class="capacity-memory">' + escapeHtml(cap.memory) + '</div>';
                const opt = document.createElement('option');
                opt.value = cap.qpod;
                opt.textContent = cap.qpod + ' - ' + cap.memory;
                sel.appendChild(opt);
            } else {
                card.innerHTML =
                    '<div class="capacity-header">❌ ' + escapeHtml(cap.qpod) + '</div>' +
                    '<div class="capacity-error">Error: ' + escapeHtml(cap.error) + '</div>';
            }
            results.appendChild(card);
        });

        if (hasSuccess) selectorSection.style.display = 'block';
        showAlert('QPod capacities loaded!', 'success');
    } catch(e) {
        loading.style.display = 'none';
        showAlert('Failed to check capacities: ' + e.message, 'error');
    }
}

function showAlert(msg, type) {
    const a = document.getElementById('alert');
    a.textContent = msg; 
    a.className = 'alert alert-' + type + ' show';
    
    // Scroll to alert and add shake animation for errors
    if (type === 'error') {
        a.classList.add('shake');
        setTimeout(() => a.classList.remove('shake'), 500);
    }
    
    // Smooth scroll to alert
    a.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideAlert() { 
    const a = document.getElementById('alert'); 
    a.className = 'alert';
    a.classList.remove('shake');
}

// ── Profile Version management ────────────────────────────────────────────────
const DEFAULT_PROFILE_VERSIONS = ['2.7.0', '2.8.0', '2.9.0', '3.0.0'];

function loadProfileVersions() {
    const stored = localStorage.getItem('profileVersions');
    let versions = DEFAULT_PROFILE_VERSIONS.slice();
    if (stored) { try { versions = JSON.parse(stored); } catch(e) {} }
    const sel = document.getElementById('profile-version');
    sel.innerHTML = '';
    versions.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v;
        opt.textContent = 'release_' + v + '_vmm_3.0';
        sel.appendChild(opt);
    });
    renderProfileVersionTags(versions);
}

function saveProfileVersions(versions) {
    localStorage.setItem('profileVersions', JSON.stringify(versions));
}

function getProfileVersions() {
    const stored = localStorage.getItem('profileVersions');
    if (stored) { try { return JSON.parse(stored); } catch(e) {} }
    return DEFAULT_PROFILE_VERSIONS.slice();
}

function addProfileVersion() {
    const input = document.getElementById('new-profile-version');
    const v = input.value.trim();
    if (!v) { showAlert('Enter a version number', 'error'); return; }
    if (!/^[0-9]+\.[0-9]+\.[0-9]+$/.test(v)) { showAlert('Use format X.Y.Z (e.g. 3.1.0)', 'error'); return; }
    const versions = getProfileVersions();
    if (versions.includes(v)) { showAlert('Version already exists', 'error'); return; }
    versions.push(v);
    saveProfileVersions(versions);
    loadProfileVersions();
    document.getElementById('profile-version').value = v;
    input.value = '';
    showAlert('Version ' + v + ' added!', 'success');
}

function removeProfileVersion(v) {
    const versions = getProfileVersions().filter(x => x !== v);
    if (versions.length === 0) { showAlert('Must keep at least one version', 'error'); return; }
    saveProfileVersions(versions);
    loadProfileVersions();
}

function renderProfileVersionTags(versions) {
    const container = document.getElementById('profile-version-tags');
    container.innerHTML = '';
    versions.forEach(v => {
        const isDefault = DEFAULT_PROFILE_VERSIONS.includes(v);
        const tag = document.createElement('div');
        tag.className = 'col-tag active';
        tag.title = 'release_' + v + '_vmm_3.0';
        tag.innerHTML = v + (isDefault ? '' :
            ` <button class="col-remove" title="Remove" onclick="removeProfileVersion('${v}')">×</button>`);
        container.appendChild(tag);
    });
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadBuildStatuses();
    loadColConfig();
    renderColTags();
    loadProfileVersions();
    loadQpods();       // loads custom QPods from localStorage + renders all tags
    loadBuilds();
});
</script>
</body>
</html>
"""


def fetch_builds():
    try:
        response = requests.get(OVA_BASE_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        builds = []

        pre_tag = soup.find("pre")
        source = pre_tag.get_text() if pre_tag else soup.get_text()

        pattern = (
            r"((?:develop\.|eop-)[^\s]+/)\s+(\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2})"
        )
        for line in source.split("\n"):
            if ("develop." in line or "eop-" in line) and "/" in line:
                match = re.search(pattern, line)
                if match:
                    build_name = match.group(1).rstrip("/")
                    builds.append(
                        {
                            "name": build_name,
                            "url": OVA_BASE_URL + build_name + "/",
                            "date": match.group(2),
                        }
                    )

        if not builds:
            for link in soup.find_all("a"):
                href = link.get("href", "")
                if (
                    href.startswith("develop.") or href.startswith("eop-")
                ) and href.endswith("/"):
                    builds.append(
                        {
                            "name": href.rstrip("/"),
                            "url": OVA_BASE_URL + href,
                            "date": "N/A",
                        }
                    )

        # Sort by date (newest first) - parse date format "02-Mar-2024 12:34"
        def parse_build_date(build):
            try:
                if build["date"] != "N/A":
                    return datetime.strptime(build["date"], "%d-%b-%Y %H:%M")
                return datetime.min
            except:
                return datetime.min
        
        builds.sort(key=parse_build_date, reverse=True)
        print(f"Found {len(builds)} builds")
        return builds
    except Exception as e:
        print(f"Error fetching builds: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


def fetch_image_version(build_url, image_key):
    """
    Fetch version for any image key from images.txt.
    image_key can be a partial name like 'papi', 'alert-manager',
    or a full path like 'mistsys/epic-ui'.
    """
    try:
        images_url = build_url + "images.txt"
        response = requests.get(images_url, timeout=10)
        response.raise_for_status()
        content = response.text

        key_lower = image_key.lower()

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            colon_pos = line.rfind(":")
            if colon_pos == -1:
                continue
            image_path = line[:colon_pos].lower()
            version = line[colon_pos + 1:]

            if (
                image_path == key_lower
                or image_path.endswith("/" + key_lower)
                or key_lower in image_path
            ):
                return version.strip() if version.strip() else "N/A"

        return "N/A"
    except Exception as e:
        print(f"Error fetching image version ({image_key}) from {build_url}: {e}")
        return "Error"


def check_qpod_capacity(qpod, unix_id, password):
    ssh_host = f"{qpod}.{SSH_DOMAIN}"
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ssh_host, username=unix_id, password=password, timeout=15)
        _, stdout, stderr = ssh.exec_command("vmm capacity -g vmm-default")
        output = stdout.read().decode("utf-8")
        error = stderr.read().decode("utf-8")
        ssh.close()

        if error and not output:
            return {
                "qpod": qpod,
                "status": "error",
                "error": error.strip(),
                "memory": "N/A",
            }

        memory_info = "N/A"
        for line in output.split("\n"):
            if "memory" in line.lower() or "mem" in line.lower():
                memory_info = line.strip()
                break
        if memory_info == "N/A" and output.strip():
            memory_info = output.strip()

        return {
            "qpod": qpod,
            "status": "success",
            "memory": memory_info,
            "full_output": output,
        }
    except paramiko.AuthenticationException:
        return {
            "qpod": qpod,
            "status": "error",
            "error": "Authentication failed",
            "memory": "N/A",
        }
    except Exception as e:
        return {"qpod": qpod, "status": "error", "error": str(e), "memory": "N/A"}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        ssh_domain=SSH_DOMAIN,
        setup_script=SETUP_SCRIPT,
        current_year=datetime.now().year,
        qpods_json=Markup(json.dumps(QPODS)), # ← injects QPODS into JS as DEFAULT_QPODS
    )


@app.route("/api/builds")
def get_builds():
    return jsonify(fetch_builds())


@app.route("/api/image-version/<path:build_name>")
def get_image_version(build_name):
    """Return version for an arbitrary image key from images.txt."""
    image_key = request.args.get("image", "epic-ui")
    build_url = OVA_BASE_URL + build_name + "/"
    version = fetch_image_version(build_url, image_key)
    return jsonify({"build_name": build_name, "image": image_key, "version": version})


@app.route("/api/check-capacity", methods=["POST"])
def check_capacity():
    data = request.json
    unix_id = data.get("unix_id")
    password = data.get("password")
    custom_qpods = data.get("custom_qpods", [])
    if not unix_id or not password:
        return jsonify({"error": "Unix ID and password required"}), 400

    # Merge default QPODS (server-side) with custom ones from frontend
    all_qpods = list(dict.fromkeys(QPODS + custom_qpods))  # preserves order, deduplicates

    from concurrent.futures import ThreadPoolExecutor, as_completed

    capacities = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_qpod = {
            executor.submit(check_qpod_capacity, q, unix_id, password): q
            for q in all_qpods
        }
        for future in as_completed(future_to_qpod):
            try:
                capacities.append(future.result())
            except Exception as e:
                capacities.append(
                    {
                        "qpod": future_to_qpod[future],
                        "status": "error",
                        "error": str(e),
                        "memory": "N/A",
                    }
                )

    capacities.sort(key=lambda x: x["qpod"])
    return jsonify(capacities)


# ── WebSocket handlers ────────────────────────────────────────────────────────

@socketio.on("execute_command")
def handle_execute_command(data):
    session_id = request.sid
    command = data.get("command", "").strip()
    if not command:
        return

    def run_command():
        try:
            import pty, fcntl, time

            master, slave = pty.openpty()
            flags = fcntl.fcntl(master, fcntl.F_GETFL)
            fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            import subprocess

            process = subprocess.Popen(
                ["/bin/bash", "-i"],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                preexec_fn=os.setsid,
            )
            os.close(slave)
            time.sleep(0.1)
            os.write(master, (command + "\n").encode())
            active_sessions[session_id] = {"process": process, "master": master}

            while True:
                try:
                    out = os.read(master, 4096).decode("utf-8", errors="replace")
                    if out:
                        socketio.emit("output", {"data": out}, room=session_id)
                except OSError:
                    pass
                if process.poll() is not None:
                    time.sleep(0.2)
                    try:
                        out = os.read(master, 4096).decode("utf-8", errors="replace")
                        if out:
                            socketio.emit("output", {"data": out}, room=session_id)
                    except:
                        pass
                    break
                time.sleep(0.05)

            socketio.emit(
                "command_ended", {"exit_code": process.poll()}, room=session_id
            )
            try:
                os.close(master)
            except:
                pass
            active_sessions.pop(session_id, None)
        except Exception as e:
            socketio.emit("error", {"error": str(e)}, room=session_id)
            active_sessions.pop(session_id, None)

    threading.Thread(target=run_command, daemon=True).start()


@socketio.on("connect_ssh")
def handle_connect_ssh(data):
    session_id = request.sid
    unix_id = data.get("unix_id")
    password = data.get("password")
    qpod = data.get("qpod")
    if not all([unix_id, password, qpod]):
        emit("error", {"error": "Missing required parameters"})
        return

    ssh_host = f"{qpod}.{SSH_DOMAIN}"

    def run():
        try:
            import time

            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            socketio.emit(
                "output", {"data": f"Connecting to {ssh_host}...\r\n"}, room=session_id
            )
            ssh.connect(ssh_host, username=unix_id, password=password, timeout=30)
            socketio.emit("output", {"data": "Connected!\r\n\r\n"}, room=session_id)
            channel = ssh.invoke_shell()
            active_sessions[session_id] = {"ssh": ssh, "channel": channel}
            time.sleep(1)
            while channel.recv_ready():
                socketio.emit(
                    "output",
                    {"data": channel.recv(1024).decode("utf-8", errors="replace")},
                    room=session_id,
                )
            while True:
                if channel.recv_ready():
                    out = channel.recv(1024).decode("utf-8", errors="replace")
                    if out:
                        socketio.emit("output", {"data": out}, room=session_id)
                if channel.exit_status_ready():
                    break
                time.sleep(0.05)
            exit_status = channel.recv_exit_status()
            socketio.emit(
                "output",
                {"data": f"\r\n\r\nConnection closed (exit {exit_status})\r\n"},
                room=session_id,
            )
            socketio.emit("session_ended", {"exit_code": exit_status}, room=session_id)
            channel.close()
            ssh.close()
            active_sessions.pop(session_id, None)
        except Exception as e:
            socketio.emit("error", {"error": str(e)}, room=session_id)
            active_sessions.pop(session_id, None)

    threading.Thread(target=run, daemon=True).start()


@socketio.on("monitor_deployment")
def handle_monitor_deployment(data):
    session_id = request.sid
    unix_id = data.get("unix_id")
    password = data.get("password")
    qpod = data.get("qpod")
    build_name = data.get("build_name")
    log_path = data.get("log_path")
    if not all([unix_id, password, qpod, build_name, log_path]):
        emit("deployment_status", {"build_name": build_name, "status": "failed"})
        return

    ssh_host = f"{qpod}.{SSH_DOMAIN}"

    def monitor():
        try:
            import time

            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ssh_host, username=unix_id, password=password, timeout=30)
            channel = ssh.invoke_shell()
            time.sleep(1)
            while channel.recv_ready():
                channel.recv(1024)
            channel.send(f"tail -f {log_path}\n")
            socketio.emit(
                "output",
                {"data": f"\r\n📋 Streaming logs from {log_path}...\r\n"},
                room=session_id,
            )

            start = time.time()
            last_update = time.time()
            recent_logs = []

            while True:
                if channel.recv_ready():
                    try:
                        out = channel.recv(4096).decode("utf-8", errors="replace")
                        socketio.emit("output", {"data": out}, room=session_id)
                        recent_logs.extend(out.split("\n"))
                        recent_logs = recent_logs[-10:]
                        if (
                            "Deployment success" in out
                            or "deployment completed successfully" in out.lower()
                        ):
                            socketio.emit(
                                "deployment_status",
                                {"build_name": build_name, "status": "success"},
                                room=session_id,
                            )
                            break
                        if "Deployment failed" in out or "ERROR:" in out:
                            socketio.emit(
                                "deployment_status",
                                {"build_name": build_name, "status": "failed"},
                                room=session_id,
                            )
                            break
                    except Exception:
                        pass

                if time.time() - last_update >= 30:
                    mins = int((time.time() - start) / 60)
                    clean = [
                        l.strip()
                        for l in recent_logs[-5:]
                        if l.strip()
                        and len(l.strip()) > 10
                        and not l.strip().startswith("[")
                        and "Running" not in l
                    ]
                    snippet = "\n".join(clean[-3:]) or "Processing..."
                    progress_text = f"⏱️ {mins}m\n{snippet}"
                    socketio.emit(
                        "log_progress",
                        {"build_name": build_name, "log_snippet": progress_text},
                        room=session_id,
                    )
                    socketio.emit(
                        "output",
                        {"data": f"\r\n⏱️  [{mins}m] Still deploying...\r\n"},
                        room=session_id,
                    )
                    last_update = time.time()

                if time.time() - start > 7200:
                    socketio.emit(
                        "deployment_status",
                        {"build_name": build_name, "status": "timeout"},
                        room=session_id,
                    )
                    break
                if active_sessions.get(session_id, {}).get("stopped"):
                    break
                time.sleep(1)

            try:
                channel.send("\x03")
                time.sleep(0.5)
                channel.close()
            except:
                pass
            ssh.close()
            active_sessions.pop(session_id, None)
        except Exception as e:
            socketio.emit(
                "deployment_status",
                {"build_name": build_name, "status": "failed", "error": str(e)},
                room=session_id,
            )

    threading.Thread(target=monitor, daemon=True).start()


@socketio.on("stop_monitoring")
def handle_stop_monitoring():
    session_id = request.sid
    if session_id in active_sessions:
        active_sessions[session_id]["stopped"] = True


@socketio.on("start_session")
def handle_start_session(data):
    session_id = request.sid
    unix_id = data.get("unix_id")
    password = data.get("password")
    qpod = data.get("qpod")
    build_name = data.get("build_name")
    profile_version = data.get("profile_version", DEFAULT_PROFILE_VERSION)
    if not all([unix_id, password, qpod, build_name]):
        emit("error", {"error": "Missing required parameters"})
        return

    ssh_host = f"{qpod}.{SSH_DOMAIN}"
    setup_profile = SETUP_PROFILE_BASE.format(version=profile_version)

    def run():
        try:
            import time

            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            socketio.emit(
                "output", {"data": f"Connecting to {ssh_host}...\r\n"}, room=session_id
            )
            ssh.connect(ssh_host, username=unix_id, password=password, timeout=30)
            socketio.emit(
                "output",
                {"data": "Connected!\r\n\r\nRunning ssh-add...\r\n"},
                room=session_id,
            )
            channel = ssh.invoke_shell()
            channel.send("ssh-add\n")
            time.sleep(2)
            while channel.recv_ready():
                socketio.emit(
                    "output",
                    {"data": channel.recv(1024).decode("utf-8")},
                    room=session_id,
                )

            command = f"{SETUP_SCRIPT} -n {setup_profile} -o __davinciVersion__={build_name}\n"
            socketio.emit("output", {"data": f"Executing: {command}"}, room=session_id)
            channel.send(command)
            active_sessions[session_id] = {"ssh": ssh, "channel": channel}

            while True:
                if channel.recv_ready():
                    out = channel.recv(1024).decode("utf-8", errors="replace")
                    socketio.emit("output", {"data": out}, room=session_id)
                if channel.exit_status_ready():
                    break
                time.sleep(0.05)

            exit_status = channel.recv_exit_status()
            socketio.emit(
                "output",
                {"data": f"\r\n\r\nSession ended (exit {exit_status})\r\n"},
                room=session_id,
            )
            socketio.emit("session_ended", {"exit_code": exit_status}, room=session_id)
            channel.close()
            ssh.close()
            active_sessions.pop(session_id, None)
        except Exception as e:
            socketio.emit("error", {"error": str(e)}, room=session_id)
            active_sessions.pop(session_id, None)

    threading.Thread(target=run, daemon=True).start()


@socketio.on("input")
def handle_input(data):
    session_id = request.sid
    user_input = data.get("data", "")
    if session_id in active_sessions:
        sess = active_sessions[session_id]
        if "channel" in sess:
            sess["channel"].send(user_input)
        elif "master" in sess:
            try:
                os.write(sess["master"], user_input.encode())
            except Exception as e:
                print(f"[ERROR] write to master: {e}")


@socketio.on("kill_session")
def handle_kill_session():
    session_id = request.sid
    if session_id in active_sessions and "channel" in active_sessions[session_id]:
        try:
            active_sessions[session_id]["channel"].send("\x03")
            socketio.emit("output", {"data": "\r\n^C\r\n"}, room=session_id)
        except Exception as e:
            print(f"[ERROR] Ctrl+C: {e}")


@socketio.on("disconnect")
def handle_disconnect():
    session_id = request.sid
    if session_id in active_sessions:
        try:
            active_sessions[session_id]["channel"].close()
            active_sessions[session_id]["ssh"].close()
        except:
            pass
        del active_sessions[session_id]


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Launch Setup from OVA Image")
    print(f"© HPE - {datetime.now().year}")
    print("=" * 60)
    print(f"Server: http://localhost:8080")
    print(f"OVA:    {OVA_BASE_URL}")
    print(f"QPods:  {', '.join(QPODS)}")
    print("=" * 60)
    socketio.run(app, debug=True, host="0.0.0.0", port=8080)