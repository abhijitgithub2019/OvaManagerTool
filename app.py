#!/usr/bin/env python3
"""
Simple OVA Build Manager with Python Backend
This solves CORS issues by fetching data server-side
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

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
OVA_BASE_URL = 'http://storage1.qnc.kanlab.jnpr.net/ova/'
QPODS = ['q-pod30-vmm', 'q-pod32-vmm', 'q-pod36-vmm', 'q-pod38-vmm']
SSH_DOMAIN = 'englab.juniper.net'
SETUP_SCRIPT = '/homes/jtsai/full_setup.sh'
SETUP_PROFILE_BASE = 'basicDemo-eop:profile_daily-davinci_eop_dev_release_{version}_vmm_3.0'
DEFAULT_PROFILE_VERSION = '2.7.0'

# Store active SSH sessions
active_sessions = {}

# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OVA Build Manager</title>
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
            max-width: 1200px;
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
        .builds-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        .builds-table thead { background: #495057; color: white; position: sticky; top: 0; z-index: 10; }
        .builds-table th { padding: 15px; text-align: left; font-weight: 600; }
        .builds-table td { padding: 15px; border-bottom: 1px solid #dee2e6; }
        .builds-table tbody tr:hover { background: #f8f9fa; }
        
        /* Column widths - Status column wider for log display */
        .builds-table th:nth-child(1), .builds-table td:nth-child(1) { width: 20%; }
        .builds-table th:nth-child(2), .builds-table td:nth-child(2) { width: 12%; }
        .builds-table th:nth-child(3), .builds-table td:nth-child(3) { width: 12%; }
        .builds-table th:nth-child(4), .builds-table td:nth-child(4) { width: 35%; } /* Status - wider */
        .builds-table th:nth-child(5), .builds-table td:nth-child(5) { width: 13%; }
        
        /* Status cell with wrapping */
        .status-cell {
            max-width: 350px;
            word-wrap: break-word;
            white-space: normal;
            vertical-align: top;
        }
        
        /* Progress log snippet display */
        .status-progress {
            font-size: 0.7em;
            color: #495057;
            background: #f1f3f5;
            padding: 6px 10px;
            border-radius: 4px;
            margin-top: 5px;
            font-family: 'Courier New', monospace;
            max-height: 80px;
            overflow-y: auto;
            word-wrap: break-word;
            white-space: pre-wrap;
            border-left: 3px solid #667eea;
            line-height: 1.4;
        }

        .status-progress::first-line {
            font-weight: 600;
            color: #667eea;
        }
        .table-wrapper {
            max-height: 500px;
            overflow-y: auto;
            border: 2px solid #dee2e6;
            border-radius: 8px;
        }
        .footer {
            text-align: center;
            padding: 20px;
            background: #f8f9fa;
            border-top: 2px solid #dee2e6;
            color: #6c757d;
            font-size: 0.9em;
        }
        .build-number {
            font-family: 'Courier New', monospace;
            color: #495057;
            font-weight: 600;
        }
        .epic-version {
            color: #28a745;
            font-weight: 600;
            background: #d4edda;
            padding: 5px 10px;
            border-radius: 4px;
            display: inline-block;
            width:  140px;
        }
        .status-badge {
            padding: 6px 12px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 0.85em;
            display: inline-block;
            min-width: 90px;
            text-align: center;
        }
        .status-pending {
            background: #fff3cd;
            color: #856404;
            border: 1px solid #ffeaa7;
        }
        .status-deploying {
            background: #cce5ff;
            color: #004085;
            border: 1px solid #b8daff;
            animation: pulse 2s infinite;
        }
        .status-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .status-failed {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .status-stopped {
            background: #e2e3e5;
            color: #383d41;
            border: 1px solid #d6d8db;
        }
        .status-none {
            background: #f8f9fa;
            color: #6c757d;
            border: 1px solid #dee2e6;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        .stop-btn {
            background: #dc3545;
            color: white;
            border: none;
            padding: 4px 10px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.85em;
            margin-left: 5px;
        }
        .stop-btn:hover {
            background: #c82333;
        }
        .create-btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
        }
        .create-btn:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        .create-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .alert {
            padding: 15px 20px;
            border-radius: 6px;
            margin-bottom: 20px;
            display: none;
        }
        .alert.show { display: block; }
        .alert-success { background: #d4edda; color: #155724; border-left: 4px solid #28a745; }
        .alert-error { background: #f8d7da; color: #721c24; border-left: 4px solid #dc3545; }
        .alert-info { background: #d1ecf1; color: #0c5460; border-left: 4px solid #17a2b8; }
        .refresh-btn {
            background: #28a745;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            margin-bottom: 20px;
        }
        .command-display {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
            border: 2px solid #dee2e6;
            display: none;
        }
        .command-display h3 { color: #495057; margin-bottom: 10px; }
        .command-display pre {
            background: #2d2d2d;
            color: #f8f8f2;
            padding: 15px;
            border-radius: 6px;
            overflow-x: auto;
        }
        .copy-btn {
            background: #6c757d;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            margin-top: 10px;
        }
        .capacity-card {
            background: white;
            border: 2px solid #dee2e6;
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 10px;
            transition: border-color 0.3s;
        }
        .capacity-card:hover {
            border-color: #667eea;
        }
        .capacity-card.success {
            border-left: 4px solid #28a745;
        }
        .capacity-card.error {
            border-left: 4px solid #dc3545;
        }
        .capacity-header {
            font-weight: 600;
            color: #495057;
            font-size: 1.1em;
            margin-bottom: 8px;
        }
        .capacity-memory {
            color: #28a745;
            font-family: 'Courier New', monospace;
            background: #f8f9fa;
            padding: 8px;
            border-radius: 4px;
            margin-top: 5px;
        }
        .capacity-error {
            color: #dc3545;
            font-size: 0.9em;
        }
        .terminal-container {
            background: #1e1e1e;
            border-radius: 8px;
            padding: 20px;
            margin-top: 20px;
            display: none;
        }
        .terminal-header {
            background: #2d2d2d;
            padding: 10px 15px;
            border-radius: 6px 6px 0 0;
            margin: -20px -20px 10px -20px;
            color: #fff;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .terminal-controls button {
            background: #dc3545;
            color: white;
            border: none;
            padding: 5px 15px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.9em;
        }
        .terminal-controls button:hover {
            background: #c82333;
        }
        #terminal {
            height: 400px;
        }
        .table-container {
            max-height: 500px;
            overflow-y: auto;
            border: 2px solid #dee2e6;
            border-radius: 8px;
        }
        .footer {
            text-align: center;
            padding: 20px;
            color: #6c757d;
            font-size: 0.9em;
            border-top: 2px solid #e9ecef;
            margin-top: 30px;
        }
        .info-note {
            background: #e7f3ff;
            border-left: 4px solid #2196F3;
            padding: 15px;
            margin: 20px 0;
            border-radius: 4px;
            color: #0c5460;
        }
        .info-note strong {
            color: #1976D2;
        }
        .custom-qpod-input {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        .custom-qpod-input input {
            flex: 1;
            padding: 10px;
            border: 2px solid #dee2e6;
            border-radius: 6px;
        }
        .custom-qpod-input button {
            padding: 10px 20px;
            background: #17a2b8;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 OVA Build Manager</h1>
            <p>Automated Build Deployment System</p>
        </div>
        <div class="content">
            <div class="credentials-section">
                <h2>SSH Credentials & Configuration</h2>
                <div class="input-group">
                    <div class="input-wrapper">
                        <label for="unix-id">Unix ID:</label>
                        <input type="text" id="unix-id" placeholder="Enter your Unix ID">
                    </div>
                    <div class="input-wrapper">
                        <label for="password">Password:</label>
                        <div style="position: relative;">
                            <input type="password" id="password" placeholder="Enter your password" style="padding-right: 45px;">
                            <button 
                                type="button" 
                                onclick="togglePassword()" 
                                style="position: absolute; right: 5px; top: 50%; transform: translateY(-50%); background: transparent; border: none; cursor: pointer; font-size: 1.2em; padding: 5px 10px;"
                                title="Show/Hide password"
                            >
                                <span id="password-toggle-icon">👁️</span>
                            </button>
                        </div>
                    </div>
                    <div class="input-wrapper">
                        <label for="profile-version">Profile Version:</label>
                        <input type="text" id="profile-version" placeholder="2.7.0" value="2.7.0">
                    </div>
                </div>
                <button class="refresh-btn" onclick="checkCapacities()" style="margin-top: 15px;">
                    🔍 Check QPod Capacities
                </button>
                <button class="refresh-btn" onclick="openBlankTerminal()" style="margin-top: 15px; margin-left: 10px; background: #28a745;">
                    💻 Just Open Terminal
                </button>
            </div>
            
            <div id="capacity-section" style="display: none; margin-bottom: 30px;">
                <div class="credentials-section">
                    <h2>QPod Capacity</h2>
                    <div id="capacity-loading" class="loading" style="display: none; padding: 20px;">
                        <div class="spinner"></div>
                        <p>Checking QPod capacities...</p>
                    </div>
                    <div id="capacity-results"></div>
                    <div class="custom-qpod-input">
                        <input type="text" id="custom-qpod" placeholder="Add custom QPod (e.g., q-pod40-vmm)">
                        <button onclick="addCustomQpod()">+ Add QPod</button>
                    </div>
                    <div style="margin-top: 15px;">
                        <label style="font-weight: 600; color: #495057; margin-bottom: 10px; display: block;">
                            Select QPod:
                        </label>
                        <select id="qpod-select" style="width: 100%; padding: 12px; border: 2px solid #dee2e6; border-radius: 6px; font-size: 1em;">
                            <option value="">Choose a QPod...</option>
                        </select>
                        <button class="refresh-btn" onclick="connectToQpod()" style="margin-top: 10px; background: #17a2b8;">
                            🔌 Connect to QPod (SSH Only)
                        </button>
                    </div>
                    <div class="info-note" style="margin-top: 15px;">
                        <strong>📝 Note:</strong> To view the UI IP address after deployment, run the command: <code style="background: #fff; padding: 2px 6px; border-radius: 3px; color: #d63384;">vmm ip -a</code>
                    </div>
                </div>
            </div>
            
            <div class="alert" id="alert"></div>
            
            <!-- Profile Version Selector -->
            <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 2px solid #e9ecef;">
                <label style="font-weight: 600; color: #495057; margin-bottom: 10px; display: block;">
                    Profile Release Version:
                </label>
                <select id="profile-version" style="width: 100%; padding: 12px; border: 2px solid #dee2e6; border-radius: 6px; font-size: 1em;">
                    <option value="2.7.0" selected>release_2.7.0_vmm_3.0</option>
                    <option value="2.8.0">release_2.8.0_vmm_3.0</option>
                    <option value="2.9.0">release_2.9.0_vmm_3.0</option>
                    <option value="3.0.0">release_3.0.0_vmm_3.0</option>
                </select>
            </div>

            <button class="refresh-btn" onclick="loadBuilds()">🔄 Refresh Builds</button>
            
            <!-- Search Box -->
            <div style="margin-top: 20px; margin-bottom: 15px;">
                <input 
                    type="text" 
                    id="build-search" 
                    placeholder="🔍 Search builds by name, date, or EPIC version..." 
                    oninput="filterBuilds()"
                    style="width: 100%; padding: 12px; border: 2px solid #dee2e6; border-radius: 6px; font-size: 1em; box-sizing: border-box;"
                />
                <div id="search-results" style="margin-top: 10px; color: #6c757d; font-size: 0.9em;"></div>
            </div>
            
            <div class="loading" id="loading">
                <div class="spinner"></div>
                <p>Loading available builds...</p>
            </div>
            <div id="builds-container" style="display: none;">
                <div class="table-wrapper">
                    <table class="builds-table">
                        <thead>
                            <tr>
                                <th>Build Number</th>
                                <th>Date</th>
                                <th>EPIC Version</th>
                                <th>Status & Progress</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody id="builds-tbody"></tbody>
                    </table>
                </div>
            </div>
            <div class="command-display" id="command-display" style="display: none;">
                <h3>SSH Command to Execute:</h3>
                <pre id="command-text"></pre>
                <button class="copy-btn" onclick="copyCommand()">📋 Copy Command</button>
            </div>
            
            <!-- Terminals Container - Supports Multiple Terminals -->
            <div id="terminals-container" style="margin-top: 20px;"></div>
            
            <!-- Footer -->
            <div class="footer">
                © HPE {{ current_year }} - All Rights Reserved
            </div>
        </div>
    </div>
    
    <!-- Footer -->
    <div class="footer">
        <p>© HPE - <span id="current-year"></span> | OVA Build Manager</p>
    </div>
    
    <script>
        // Set current year
        document.getElementById('current-year').textContent = new Date().getFullYear();
    </script>
    <script>
        const SSH_DOMAIN = '{{ ssh_domain }}';
        const SETUP_SCRIPT = '{{ setup_script }}';
        const SETUP_PROFILE = '{{ setup_profile }}';
        
        let builds = [];
        let customQpods = [];
        let buildStatuses = {};
        let activeDeployments = {};
        let terminals = [];  // Array to store multiple terminals
        let terminalSockets = [];  // Array to store multiple sockets
        
        document.addEventListener('DOMContentLoaded', function() {
            loadBuildStatuses();
            loadBuilds();
        });

        function togglePassword() {
            const passwordInput = document.getElementById('password');
            const toggleIcon = document.getElementById('password-toggle-icon');
            
            if (passwordInput.type === 'password') {
                passwordInput.type = 'text';
                toggleIcon.textContent = '🙈';  // Hide icon
            } else {
                passwordInput.type = 'password';
                toggleIcon.textContent = '👁️';  // Show icon
            }
        }

        function loadBuildStatuses() {
            const stored = localStorage.getItem('buildStatuses');
            if (stored) {
                try {
                    buildStatuses = JSON.parse(stored);
                } catch (e) {
                    buildStatuses = {};
                }
            }
        }

        function saveBuildStatuses() {
            localStorage.setItem('buildStatuses', JSON.stringify(buildStatuses));
        }

        function getBuildStatus(buildName) {
            return buildStatuses[buildName] || { status: 'none', timestamp: null, qpod: null, progress: '' };
        }

        function setBuildStatus(buildName, status, qpod, progress) {
            buildStatuses[buildName] = {
                status: status,
                timestamp: new Date().toISOString(),
                qpod: qpod || buildStatuses[buildName]?.qpod,
                progress: progress || buildStatuses[buildName]?.progress || ''
            };
            saveBuildStatuses();
            updateBuildStatusDisplay(buildName);
        }

        function updateBuildStatusDisplay(buildName) {
            const row = document.querySelector('[data-build-name="' + buildName.toLowerCase() + '"]');
            if (row) {
                const statusCell = row.querySelector('.status-cell');
                if (statusCell) {
                    statusCell.innerHTML = getStatusHTML(buildName);
                }
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function getStatusHTML(buildName) {
            const statusInfo = getBuildStatus(buildName);
            const status = statusInfo.status;
            const progress = statusInfo.progress || \'\';
            
            let badge = '';
            let stopBtn = '';
            let progressDiv = \'\';
            
            switch(status) {
                case 'pending':
                    badge = '<span class="status-badge status-pending">⏳ Started</span>';
                    break;
                case 'deploying':
                    badge = '<span class="status-badge status-deploying">🚀 Deploying</span>';
                    stopBtn = '<button class="stop-btn" onclick="stopDeployment(\\\'' + buildName + '\\\')">Stop Monitoring</button>';
                    if (progress) {
                      progressDiv = '<div class="status-progress">' + escapeHtml(progress) + '</div>';
                    }
                    break;
                case 'success':
                    badge = '<span class="status-badge status-success">✅ Success</span>';
                    break;
                case 'failed':
                    badge = '<span class="status-badge status-failed">❌ Failed</span>';
                    break;
                case 'stopped':
                    badge = '<span class="status-badge status-stopped">⏹️ Stopped</span>';
                    break;
                default:
                    badge = '<span class="status-badge status-none">Not Started</span>';
            }
            
            return '<div>' + badge + stopBtn + progressDiv + '</div>';
        }

        function stopDeployment(buildName) {
            if (confirm('Stop deployment monitoring for ' + buildName + '?')) {
                setBuildStatus(buildName, 'stopped', null);
                
                if (activeDeployments[buildName]) {
                    // Send stop signal to backend
                    activeDeployments[buildName].emit('stop_monitoring');
                    // Disconnect the monitoring socket
                    activeDeployments[buildName].disconnect();
                    delete activeDeployments[buildName];
                }
                
                showAlert('Deployment monitoring stopped for ' + buildName, 'info');
            }
        }

        document.addEventListener('DOMContentLoaded', loadBuilds);

        function addCustomQpod() {
            const input = document.getElementById('custom-qpod');
            const qpod = input.value.trim();
            
            if (!qpod) {
                showAlert('Please enter a QPod name', 'error');
                return;
            }
            
            if (!qpod.includes('vmm')) {
                showAlert('QPod name should contain "vmm" (e.g., q-pod40-vmm)', 'error');
                return;
            }
            
            if (customQpods.includes(qpod)) {
                showAlert('This QPod is already added', 'error');
                return;
            }
            
            customQpods.push(qpod);
            input.value = '';
            showAlert('QPod added: ' + qpod + '. Click "Check QPod Capacities" to verify.', 'success');
        }

        function connectToQpod() {
            const unixId = document.getElementById('unix-id').value.trim();
            const password = document.getElementById('password').value;
            const qpod = document.getElementById('qpod-select').value;

            if (!unixId || !password) {
                showAlert('Please enter Unix ID and Password', 'error');
                return;
            }

            if (!qpod) {
                showAlert('Please select a QPod first', 'error');
                return;
            }

            // Open terminal for simple SSH connection
            openTerminalForSSH(unixId, password, qpod);
        }

        function openTerminalForSSH(unixId, password, qpod) {
            // Create unique terminal ID
            const terminalId = 'terminal-' + Date.now();
            
            // Create terminal container
            const terminalsContainer = document.getElementById('terminals-container');
            const terminalContainer = document.createElement('div');
            terminalContainer.className = 'terminal-container';
            terminalContainer.id = terminalId + '-container';
            terminalContainer.style.marginBottom = '20px';
            terminalContainer.style.display = 'block';  // Make terminal visible
            terminalContainer.innerHTML = 
                '<div class="terminal-header">' +
                    '<span>🔌 SSH Connection - ' + qpod + '</span>' +
                    '<div class="terminal-controls">' +
                        '<button onclick="sendCtrlCToTerminal(\\\'' + terminalId + '\\\')" style="background: #ffc107; margin-right: 10px;">Ctrl+C</button>' +
                        '<button onclick="closeTerminal(\\\'' + terminalId + '\\\')">Close</button>' +
                    '</div>' +
                '</div>' +
                '<div id="' + terminalId + '"></div>';
            
            terminalsContainer.appendChild(terminalContainer);
            
            // Create new terminal
            const term = new Terminal({
                cursorBlink: true,
                fontSize: 14,
                fontFamily: 'Menlo, Monaco, "Courier New", monospace',
                theme: {
                    background: '#1e1e1e',
                    foreground: '#f0f0f0',
                    cursor: '#f0f0f0',
                    selection: 'rgba(255, 255, 255, 0.3)',
                    black: '#000000',
                    red: '#e74856',
                    green: '#16c60c',
                    yellow: '#f9f1a5',
                    blue: '#3b78ff',
                    magenta: '#b4009e',
                    cyan: '#61d6d6',
                    white: '#f0f0f0'
                }
            });
            
            const fitAddon = new FitAddon.FitAddon();
            term.loadAddon(fitAddon);
            term.open(document.getElementById(terminalId));
            fitAddon.fit();
            term.focus();  // Auto-focus for input
            
            // Scroll to new terminal
            terminalContainer.scrollIntoView({ behavior: 'smooth' });
            
            // Write header
            term.writeln('\\x1b[1;36m🔌 SSH Connection to QPod\\x1b[0m');
            term.writeln('\\x1b[90m' + '='.repeat(60) + '\\x1b[0m');
            term.writeln('\\x1b[1;33mQPod:\\x1b[0m ' + qpod + '.' + SSH_DOMAIN);
            term.writeln('\\x1b[1;33mUser:\\x1b[0m ' + unixId);
            term.writeln('\\x1b[90m' + '='.repeat(60) + '\\x1b[0m');
            term.writeln('');
            
            // Connect to WebSocket
            const socket = io();
            
            // Store terminal and socket
            terminals.push({ id: terminalId, term: term, fitAddon: fitAddon });
            terminalSockets.push({ id: terminalId, socket: socket });
            
            // Handle terminal input - send to server
            term.onData(function(data) {
                socket.emit('input', { data: data });
            });
            
            // Handle output from server
            socket.on('output', function(msg) {
                term.write(msg.data);
            });
            
            // Handle errors
            socket.on('error', function(msg) {
                term.writeln('\\r\\n\\x1b[1;31mError: ' + msg.error + '\\x1b[0m\\r\\n');
                showAlert('Error: ' + msg.error, 'error');
            });
            
            // Handle session end
            socket.on('session_ended', function(msg) {
                term.writeln('\\r\\n\\x1b[1;32m✓ Session ended\\x1b[0m\\r\\n');
                showAlert('SSH session ended', 'info');
            });
            
            // Start the SSH connection
            socket.emit('connect_ssh', {
                unix_id: unixId,
                password: password,
                qpod: qpod
            });
        }

        function openBlankTerminal() {
            // Create unique terminal ID
            const terminalId = 'terminal-' + Date.now();
            
            // Create terminal container
            const terminalsContainer = document.getElementById('terminals-container');
            const terminalContainer = document.createElement('div');
            terminalContainer.className = 'terminal-container';
            terminalContainer.id = terminalId + '-container';
            terminalContainer.style.marginBottom = '20px';
            terminalContainer.style.display = 'block';  // Make terminal visible
            terminalContainer.innerHTML = 
                '<div class="terminal-header">' +
                    '<span>💻 Interactive Terminal</span>' +
                    '<div class="terminal-controls">' +
                        '<button onclick="sendCtrlCToTerminal(\\\'' + terminalId + '\\\')" style="background: #ffc107; margin-right: 10px;">Ctrl+C</button>' +
                        '<button onclick="closeTerminal(\\\'' + terminalId + '\\\')">Close</button>' +
                    '</div>' +
                '</div>' +
                '<div id="' + terminalId + '"></div>';
            
            terminalsContainer.appendChild(terminalContainer);
            
            // Create new terminal
            const term = new Terminal({
                cursorBlink: true,
                fontSize: 14,
                fontFamily: 'Menlo, Monaco, "Courier New", monospace',
                theme: {
                    background: '#1e1e1e',
                    foreground: '#f0f0f0',
                    cursor: '#f0f0f0',
                    selection: 'rgba(255, 255, 255, 0.3)',
                    black: '#000000',
                    red: '#e74856',
                    green: '#16c60c',
                    yellow: '#f9f1a5',
                    blue: '#3b78ff',
                    magenta: '#b4009e',
                    cyan: '#61d6d6',
                    white: '#f0f0f0'
                }
            });
            
            const fitAddon = new FitAddon.FitAddon();
            term.loadAddon(fitAddon);
            term.open(document.getElementById(terminalId));
            fitAddon.fit();
            term.focus();  // Auto-focus for input
            
            // Scroll to new terminal
            terminalContainer.scrollIntoView({ behavior: 'smooth' });
            
            // Write welcome message
            term.writeln('\\x1b[1;36m💻 Interactive Terminal\x1b[0m');
            term.writeln('\\x1b[90m' + '='.repeat(60) + '\\x1b[0m');
            term.writeln('');
            term.writeln('\\x1b[1;33mType any command and press Enter to execute.\x1b[0m');
            term.writeln('Examples:');
            term.writeln('  \\x1b[32mssh apatra@q-pod30-vmm.englab.juniper.net\\x1b[0m');
            term.writeln('  \\x1b[32mls -la\\x1b[0m');
            term.writeln('  \\x1b[32mpwd\\x1b[0m');
            term.writeln('');
            term.writeln('\\x1b[90m' + '='.repeat(60) + '\\x1b[0m');
            term.writeln('');
            term.write('$ ');
            
            // Connect to WebSocket
            const socket = io();
            
            // Store terminal and socket
            terminals.push({ id: terminalId, term: term, fitAddon: fitAddon });
            terminalSockets.push({ id: terminalId, socket: socket });
            
            // Local echo buffer
            let commandBuffer = '';
            let isExecuting = false;
            
            // Handle command output from server
            socket.on('output', function(msg) {
                term.write(msg.data);
            });
            
            // Handle command ended
            socket.on('command_ended', function(msg) {
                isExecuting = false;
                term.write('\\r\\n$ ');
                commandBuffer = '';
            });
            
            // Handle errors
            socket.on('error', function(msg) {
                term.writeln('\\r\\n\\x1b[1;31mError: ' + msg.error + '\\x1b[0m\\r\\n');
                isExecuting = false;
                term.write('$ ');
                commandBuffer = '';
            });
            
            // Handle local terminal input
            term.onData(function(data) {
                if (isExecuting) {
                    // If a command is running, send input to it (for SSH password, prompts, etc.)
                    socket.emit('input', { data: data });
                    return;
                }
                
                const code = data.charCodeAt(0);
                
                // Handle special keys
                if (data === '\\r' || data === '\\n') {
                    // Enter key
                    term.write('\\r\\n');
                    
                    if (commandBuffer.trim()) {
                        isExecuting = true;
                        // Execute the command
                        socket.emit('execute_command', { command: commandBuffer.trim() });
                    } else {
                        term.write('$ ');
                    }
                    
                    commandBuffer = '';
                } else if (code === 127 || code === 8) {
                    // Backspace (127) or Delete (8)
                    if (commandBuffer.length > 0) {
                        commandBuffer = commandBuffer.slice(0, -1);
                        term.write('\\b \\b');
                    }
                } else if (code === 3) {
                    // Ctrl+C
                    if (isExecuting) {
                        socket.emit('kill_session');
                    }
                    term.write('^C\\r\\n$ ');
                    commandBuffer = '';
                    isExecuting = false;
                } else if (code === 9) {
                    // Tab - just add it
                    commandBuffer += data;
                    term.write(data);
                } else if (code >= 32 && code < 127) {
                    // Printable ASCII characters
                    commandBuffer += data;
                    term.write(data);
                }
                // Ignore other control characters
            });
            
            showAlert('Interactive terminal opened! Type commands and press Enter.', 'success');
        }

        async function checkCapacities() {
            const unixId = document.getElementById('unix-id').value.trim();
            const password = document.getElementById('password').value;

            if (!unixId || !password) {
                showAlert('Please enter Unix ID and Password first', 'error');
                return;
            }

            const capacitySection = document.getElementById('capacity-section');
            const capacityLoading = document.getElementById('capacity-loading');
            const capacityResults = document.getElementById('capacity-results');
            const qpodSelect = document.getElementById('qpod-select');

            capacitySection.style.display = 'block';
            capacityLoading.style.display = 'block';
            capacityResults.innerHTML = '';
            qpodSelect.innerHTML = '<option value="">Choose a QPod...</option>';
            hideAlert();

            try {
                const response = await fetch('/api/check-capacity', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        unix_id: unixId, 
                        password: password,
                        custom_qpods: customQpods
                    })
                });

                const capacities = await response.json();
                capacityLoading.style.display = 'none';

                if (capacities.error) {
                    showAlert('Error: ' + capacities.error, 'error');
                    return;
                }

                // Display capacity cards
                capacities.forEach(cap => {
                    const card = document.createElement('div');
                    card.className = 'capacity-card ' + cap.status;
                    
                    if (cap.status === 'success') {
                        card.innerHTML = 
                            '<div class="capacity-header">📊 ' + cap.qpod + '</div>' +
                            '<div class="capacity-memory">' + cap.memory + '</div>';
                        // Add to dropdown
                        const option = document.createElement('option');
                        option.value = cap.qpod;
                        option.textContent = cap.qpod + ' - ' + cap.memory;
                        qpodSelect.appendChild(option);
                    } else {
                        card.innerHTML = 
                            '<div class="capacity-header">❌ ' + cap.qpod + '</div>' +
                            '<div class="capacity-error">Error: ' + cap.error + '</div>';
                    }
                    
                    capacityResults.appendChild(card);
                });

                showAlert('QPod capacities loaded! (Checked in parallel)', 'success');
            } catch (error) {
                capacityLoading.style.display = 'none';
                showAlert('Failed to check capacities: ' + error.message, 'error');
            }
        }

        async function loadBuilds() {
            const loading = document.getElementById('loading');
            const container = document.getElementById('builds-container');
            loading.style.display = 'block';
            container.style.display = 'none';
            hideAlert();

            try {
                const response = await fetch('/api/builds');
                builds = await response.json();
                loading.style.display = 'none';
                
                if (builds.error) {
                    showAlert('Error: ' + builds.error, 'error');
                    return;
                }
                
                if (builds.length === 0) {
                    showAlert('No builds found', 'error');
                    return;
                }
                
                // Display builds immediately with "Loading..." for EPIC versions
                renderBuilds();
                container.style.display = 'block';
                showAlert('Loaded ' + builds.length + ' builds! Fetching EPIC versions...', 'info');
                
                // Fetch EPIC versions in background (parallel requests)
                fetchEpicVersionsAsync();
                
            } catch (error) {
                loading.style.display = 'none';
                showAlert('Failed to load builds: ' + error.message, 'error');
            }
        }

        async function fetchEpicVersionsAsync() {
            // Fetch EPIC versions in batches of 5 to avoid overwhelming the server
            const batchSize = 5;
            let completed = 0;
            
            for (let i = 0; i < builds.length; i += batchSize) {
                const batch = builds.slice(i, i + batchSize);
                
                // Fetch this batch in parallel
                await Promise.all(batch.map(async (build, batchIndex) => {
                    try {
                        const response = await fetch('/api/epic-version/' + encodeURIComponent(build.name));
                        const data = await response.json();
                        build.epic_version = data.epic_version;
                        
                        // Update the specific row in the table
                        const globalIndex = i + batchIndex;
                        const row = document.getElementById('build-row-' + globalIndex);
                        if (row) {
                            const versionCell = row.querySelector('.epic-version');
                            if (versionCell) {
                                versionCell.textContent = data.epic_version;
                            }
                        }
                        
                        completed++;
                        
                        // Update progress
                        if (completed === builds.length) {
                            showAlert('All EPIC versions loaded successfully!', 'success');
                        }
                    } catch (error) {
                        console.error('Error fetching EPIC version for ' + build.name, error);
                        build.epic_version = 'Error';
                    }
                }));
            }
        }

        function renderBuilds() {
            const tbody = document.getElementById('builds-tbody');
            tbody.innerHTML = '';
            builds.forEach((build, index) => {
                const row = document.createElement('tr');
                row.id = 'build-row-' + index;
                row.className = 'build-row';
                row.setAttribute('data-build-name', build.name.toLowerCase());
                row.setAttribute('data-build-date', (build.date || '').toLowerCase());
                row.setAttribute('data-epic-version', (build.epic_version || '').toLowerCase());
                row.innerHTML = 
                    '<td class="build-number">' + build.name + '</td>' +
                    '<td style="color: #6c757d;">' + (build.date || 'N/A') + '</td>' +
                    '<td><span class="epic-version">' + build.epic_version + '</span></td>' +
                    '<td class="status-cell">' + getStatusHTML(build.name) + '</td>' +
                    '<td>' +
                        '<button class="create-btn" onclick="createBuild(' + index + ')">' +
                            'Create Build' +
                        '</button>' +
                    '</td>';
                tbody.appendChild(row);
            });
            
            // Show total count
            updateSearchResults();
        }

        function filterBuilds() {
            const searchInput = document.getElementById('build-search');
            const filter = searchInput.value.toLowerCase();
            const rows = document.querySelectorAll('.build-row');
            let visibleCount = 0;
            
            rows.forEach(row => {
                const buildName = row.getAttribute('data-build-name');
                const buildDate = row.getAttribute('data-build-date');
                const epicVersion = row.getAttribute('data-epic-version');
                
                // Check if any field matches the search
                if (buildName.includes(filter) || 
                    buildDate.includes(filter) || 
                    epicVersion.includes(filter)) {
                    row.style.display = '';
                    visibleCount++;
                } else {
                    row.style.display = 'none';
                }
            });
            
            // Update search results message
            const searchResults = document.getElementById('search-results');
            if (filter) {
                searchResults.textContent = 'Showing ' + visibleCount + ' of ' + builds.length + ' builds';
                searchResults.style.display = 'block';
            } else {
                searchResults.textContent = '';
                searchResults.style.display = 'none';
            }
        }

        function updateSearchResults() {
            const searchInput = document.getElementById('build-search');
            if (searchInput.value) {
                filterBuilds();
            }
        }

        function createBuild(index) {
            const unixId = document.getElementById('unix-id').value.trim();
            const password = document.getElementById('password').value;
            const qpod = document.getElementById('qpod-select').value;
            const build = builds[index];

            if (!unixId || !password) {
                showAlert('Please enter Unix ID and Password', 'error');
                return;
            }

            if (!qpod) {
                showAlert('Please check capacities and select a QPod first', 'error');
                return;
            }

            // Show terminal and execute
            executeInTerminal(unixId, password, qpod, build.name);
        }

        function executeInTerminal(unixId, password, qpod, buildName) {
            console.log('executeInTerminal called:', {unixId, qpod, buildName});
            const profileVersion = document.getElementById('profile-version').value.trim() || '2.7.0';
            
            // Set initial status
            setBuildStatus(buildName, 'pending', qpod);
            
            // Create unique terminal ID
            const terminalId = 'terminal-' + Date.now();
            console.log('Created terminal ID:', terminalId);
            
            // Create terminal container
            const terminalsContainer = document.getElementById('terminals-container');
            console.log('Terminals container:', terminalsContainer);
            
            if (!terminalsContainer) {
                console.error('terminals-container not found!');
                showAlert('Error: Terminal container not found', 'error');
                return;
            }
            
            const terminalContainer = document.createElement('div');
            terminalContainer.className = 'terminal-container';
            terminalContainer.id = terminalId + '-container';
            terminalContainer.style.marginBottom = '20px';
            terminalContainer.style.display = 'block';  // Make terminal visible
            terminalContainer.innerHTML = 
                '<div class="terminal-header">' +
                    '<span>🖥️ SSH Terminal - ' + buildName + ' @ ' + qpod + '</span>' +
                    '<div class="terminal-controls">' +
                        '<button onclick="sendCtrlCToTerminal(\\\'' + terminalId + '\\\')" style="background: #ffc107; margin-right: 10px;">Ctrl+C</button>' +
                        '<button onclick="closeTerminal(\\\'' + terminalId + '\\\')">Close</button>' +
                    '</div>' +
                '</div>' +
                '<div id="' + terminalId + '"></div>';
            
            terminalsContainer.appendChild(terminalContainer);
            console.log('Terminal container appended to DOM');
            
            // Verify it's in the DOM
            const verifyDiv = document.getElementById(terminalId);
            console.log('Terminal div exists in DOM:', verifyDiv);
            
            // Create new terminal instance
            console.log('Creating Terminal instance...');
            const term = new Terminal({
                cursorBlink: true,
                fontSize: 14,
                fontFamily: 'Menlo, Monaco, "Courier New", monospace',
                theme: {
                    background: '#1e1e1e',
                    foreground: '#f0f0f0',
                    cursor: '#f0f0f0',
                    selection: 'rgba(255, 255, 255, 0.3)',
                    black: '#000000',
                    red: '#e74856',
                    green: '#16c60c',
                    yellow: '#f9f1a5',
                    blue: '#3b78ff',
                    magenta: '#b4009e',
                    cyan: '#61d6d6',
                    white: '#f0f0f0'
                }
            });
            
            const fitAddon = new FitAddon.FitAddon();
            term.loadAddon(fitAddon);
            console.log('Opening terminal in div:', terminalId);
            term.open(document.getElementById(terminalId));
            console.log('Terminal opened successfully');
            fitAddon.fit();
            console.log('Terminal fitted');
            
            // Focus the terminal so it's ready for input
            term.focus();
            console.log('Terminal focused - ready for input');
            
            // Scroll to new terminal
            terminalContainer.scrollIntoView({ behavior: 'smooth' });
            console.log('Scrolled to terminal');
            
            // Write header
            term.writeln('\\x1b[1;36m🚀 OVA Build Manager - Interactive SSH Terminal\\x1b[0m');
            term.writeln('\\x1b[90m' + '='.repeat(60) + '\\x1b[0m');
            term.writeln('\\x1b[1;33mQPod:\\x1b[0m ' + qpod + '.' + SSH_DOMAIN);
            term.writeln('\\x1b[1;33mBuild:\\x1b[0m ' + buildName);
            term.writeln('\\x1b[90m' + '='.repeat(60) + '\\x1b[0m');
            term.writeln('\\x1b[1;32m✓ Terminal ready - You can type responses to prompts\\x1b[0m');
            term.writeln('');
            
            // Connect to WebSocket
            const socket = io();
            
            // Store terminal and socket
            terminals.push({ id: terminalId, term: term, fitAddon: fitAddon });
            terminalSockets.push({ id: terminalId, socket: socket });
            
            // Handle terminal input - send to server
            term.onData(function(data) {
                socket.emit('input', { data: data });
            });
            
            // Handle output from server
            socket.on('output', function(msg) {
                term.write(msg.data);
                
                // Auto-detect deployment start and update status
                if (msg.data.includes('Please check the progress by tail')) {
                    setBuildStatus(buildName, 'deploying', qpod);
                }
            });
            
            // Handle errors
            socket.on('error', function(msg) {
                term.writeln('\\r\\n\\x1b[1;31mError: ' + msg.error + '\\x1b[0m\\r\\n');
                showAlert('Error: ' + msg.error, 'error');
                setBuildStatus(buildName, 'failed', qpod, '');
            });
            
            // Handle session end - Start monitoring deployment logs
            socket.on('session_ended', function(msg) {
                term.writeln('\\r\\n\\x1b[1;32m✓ Setup script completed\\x1b[0m\\r\\n');
                term.writeln('\\x1b[1;33m📋 Deployment started. Monitoring logs automatically...\\x1b[0m\\r\\n');
                
                // Update status to deploying
                setBuildStatus(buildName, 'deploying', qpod);
                
                // Extract QPod number for log path
                const qpodNumber = qpod.match(/q-pod(\\d+)/)?.[1] || '30';
                const logPath = '~/ns_launcher_data/q-pod' + qpodNumber + '/progress.log';
                
                term.writeln('\\r\\n\\x1b[1;36mℹ️  Auto-monitoring: ' + logPath + '\\x1b[0m\\r\\n');
                
                // Create new socket for monitoring (separate from build session)
                const monitorSocket = io();
                
                // Store for stop functionality
                activeDeployments[buildName] = monitorSocket;
                
                // Handle log progress updates (every 30 seconds for testing)
                monitorSocket.on('log_progress', function(data) {
                    console.log('[LOG_PROGRESS] Received:', data);
                    if (data.build_name === buildName) {
                        console.log('[LOG_PROGRESS] Updating status for:', buildName);
                        setBuildStatus(buildName, 'deploying', qpod, data.log_snippet);
                    }
                });
                
                // Handle deployment status updates
                monitorSocket.on('deployment_status', function(data) {
                    if (data.build_name === buildName) {
                        if (data.status === 'success') {
                            setBuildStatus(buildName, 'success', qpod, '');
                            term.writeln('\\r\\n\\x1b[1;32m✅ DEPLOYMENT SUCCESSFUL!\\x1b[0m\\r\\n');
                            showAlert('✅ Deployment successful for ' + buildName, 'success');
                            monitorSocket.disconnect();
                            delete activeDeployments[buildName];
                        } else if (data.status === 'failed') {
                            setBuildStatus(buildName, 'failed', qpod, '');
                            term.writeln('\\r\\n\\x1b[1;31m❌ DEPLOYMENT FAILED\\x1b[0m\\r\\n');
                            showAlert('❌ Deployment failed for ' + buildName, 'error');
                            monitorSocket.disconnect();
                            delete activeDeployments[buildName];
                        } else if (data.status === 'timeout') {
                            setBuildStatus(buildName, 'failed', qpod, '');
                            term.writeln('\\r\\n\\x1b[1;33m⏱️ DEPLOYMENT TIMEOUT (2 hours)\\x1b[0m\\r\\n');
                            showAlert('⏱️ Deployment timeout for ' + buildName, 'error');
                            monitorSocket.disconnect();
                            delete activeDeployments[buildName];
                        }
                    }
                });
                
                // Start monitoring
                monitorSocket.emit('monitor_deployment', {
                    unix_id: unixId,
                    password: password,
                    qpod: qpod,
                    build_name: buildName,
                    log_path: logPath
                });
                
                showAlert('Build deployment started for ' + buildName + '. Monitoring logs automatically...', 'info');
            });
            
            // Start the SSH session
            socket.emit('start_session', {
                unix_id: unixId,
                password: password,
                qpod: qpod,
                build_name: buildName,
                profile_version: profileVersion
            });
        }

        function sendCtrlCToTerminal(terminalId) {
            const socketInfo = terminalSockets.find(s => s.id === terminalId);
            if (socketInfo) {
                socketInfo.socket.emit('kill_session');
                showAlert('Sent Ctrl+C signal', 'info');
            }
        }

        function closeTerminal(terminalId) {
            // Remove terminal from DOM
            const container = document.getElementById(terminalId + '-container');
            if (container) {
                container.remove();
            }
            
            // Disconnect socket
            const socketIndex = terminalSockets.findIndex(s => s.id === terminalId);
            if (socketIndex !== -1) {
                terminalSockets[socketIndex].socket.disconnect();
                terminalSockets.splice(socketIndex, 1);
            }
            
            // Dispose terminal
            const termIndex = terminals.findIndex(t => t.id === terminalId);
            if (termIndex !== -1) {
                terminals[termIndex].term.dispose();
                terminals.splice(termIndex, 1);
            }
        }



        function copyCommand() {
            const text = document.getElementById('command-text').textContent;
            navigator.clipboard.writeText(text).then(() => {
                showAlert('Command copied to clipboard!', 'success');
            });
        }

        function showAlert(message, type) {
            const alert = document.getElementById('alert');
            alert.textContent = message;
            alert.className = 'alert alert-' + type + ' show';
        }

        function hideAlert() {
            document.getElementById('alert').className = 'alert';
        }
    </script>
</body>
</html>
'''

def fetch_builds():
    try:
        response = requests.get(OVA_BASE_URL, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        builds = []
        
        pre_tag = soup.find('pre')
        
        if pre_tag:
            lines = pre_tag.get_text().split('\n')
            for line in lines:
                if ('develop.' in line or 'eop-' in line) and '/' in line:
                    pattern = r'((?:develop\.|eop-)[^\s]+/)\s+(\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2})'
                    match = re.search(pattern, line)
                    if match:
                        build_name = match.group(1).rstrip('/')
                        date_str = match.group(2)
                        builds.append({
                            'name': build_name,
                            'url': OVA_BASE_URL + build_name + '/',
                            'date': date_str,
                            'epic_version': 'Loading...'
                        })
        
        if not builds:
            all_text = soup.get_text()
            lines = all_text.split('\n')
            for line in lines:
                if ('develop.' in line or 'eop-' in line) and '/' in line:
                    pattern = r'((?:develop\.|eop-)[^\s]+/)\s+(\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2})'
                    match = re.search(pattern, line)
                    if match:
                        build_name = match.group(1).rstrip('/')
                        date_str = match.group(2)
                        builds.append({
                            'name': build_name,
                            'url': OVA_BASE_URL + build_name + '/',
                            'date': date_str,
                            'epic_version': 'Loading...'
                        })
        
        if not builds:
            for link in soup.find_all('a'):
                href = link.get('href', '')
                if (href.startswith('develop.') or href.startswith('eop-')) and href.endswith('/'):
                    build_name = href.rstrip('/')
                    builds.append({
                        'name': build_name,
                        'url': OVA_BASE_URL + href,
                        'date': 'N/A',
                        'epic_version': 'Loading...'
                    })
        
        builds.sort(key=lambda x: x['name'], reverse=True)
        print(f"Found {len(builds)} builds")
        return builds
        
    except Exception as e:
        print(f"Error fetching builds: {e}")
        import traceback
        traceback.print_exc()
        return {'error': str(e)}

def fetch_epic_version(build_url):
    """Fetch EPIC version from images.txt"""
    try:
        images_url = build_url + 'images.txt'
        response = requests.get(images_url, timeout=10)
        response.raise_for_status()
        content = response.text
        
        # Look for pattern: mistsys/epic-ui:X.X.X-rX.X.X
        import re
        
        # Primary pattern: mistsys/epic-ui:0.369.0-r2.8.0
        epic_ui_pattern = r'mistsys/epic-ui:([0-9.]+(?:-r[0-9.]+)?)'
        match = re.search(epic_ui_pattern, content, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # Fallback patterns
        patterns = [
            r'epic[_-]?ui[:\s]+([0-9.]+(?:-r[0-9.]+)?)',
            r'epic[_-]?version[:\s]+([0-9.]+)',
            r'EPIC[_-]?VERSION[:\s]+([0-9.]+)',
            r'epic[_-]([0-9.]+)',
            r'\b(\d+\.\d+\.\d+)\b'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return 'Unknown'
    except Exception as e:
        print(f"Error fetching epic version from {build_url}: {e}")
        return 'Error'


def check_qpod_capacity(qpod, unix_id, password):
    """Check capacity of a qpod via SSH"""
    ssh_host = f"{qpod}.{SSH_DOMAIN}"
    
    try:
        # Create SSH client
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Connect
        ssh.connect(ssh_host, username=unix_id, password=password, timeout=15)
        
        # Run capacity check command
        stdin, stdout, stderr = ssh.exec_command('vmm capacity -g vmm-default')
        
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        
        ssh.close()
        
        if error and not output:
            return {
                'qpod': qpod,
                'status': 'error',
                'error': error.strip(),
                'memory': 'N/A'
            }
        
        # Parse output to extract memory information
        # Looking for lines like: "Memory: 500GB / 1000GB" or similar
        memory_info = 'N/A'
        for line in output.split('\n'):
            if 'memory' in line.lower() or 'mem' in line.lower():
                memory_info = line.strip()
                break
        
        # If no specific memory line, return full output
        if memory_info == 'N/A' and output.strip():
            memory_info = output.strip()
        
        return {
            'qpod': qpod,
            'status': 'success',
            'memory': memory_info,
            'full_output': output
        }
        
    except paramiko.AuthenticationException:
        return {
            'qpod': qpod,
            'status': 'error',
            'error': 'Authentication failed',
            'memory': 'N/A'
        }
    except Exception as e:
        return {
            'qpod': qpod,
            'status': 'error',
            'error': str(e),
            'memory': 'N/A'
        }

@app.route('/')
def index():
    """Render main page"""
    from datetime import datetime
    return render_template_string(
        HTML_TEMPLATE,
        ssh_domain=SSH_DOMAIN,
        setup_script=SETUP_SCRIPT,
        current_year=datetime.now().year
    )

@app.route('/api/builds')
def get_builds():
    """API endpoint to get builds"""
    builds = fetch_builds()
    return jsonify(builds)


@app.route('/api/epic-version/<path:build_name>')
def get_epic_version(build_name):
    """API endpoint to get EPIC version for a specific build"""
    build_url = OVA_BASE_URL + build_name + '/'
    epic_version = fetch_epic_version(build_url)
    return jsonify({'build_name': build_name, 'epic_version': epic_version})


@app.route('/api/check-capacity', methods=['POST'])
def check_capacity():
    """API endpoint to check qpod capacities in parallel"""
    data = request.json
    unix_id = data.get('unix_id')
    password = data.get('password')
    custom_qpods = data.get('custom_qpods', [])  # Allow custom QPods
    
    if not unix_id or not password:
        return jsonify({'error': 'Unix ID and password required'}), 400
    
    # Combine default QPods with custom ones
    all_qpods = list(set(QPODS + custom_qpods))
    
    # Check capacity for all qpods in parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    capacities = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit all tasks
        future_to_qpod = {
            executor.submit(check_qpod_capacity, qpod, unix_id, password): qpod 
            for qpod in all_qpods
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_qpod):
            try:
                result = future.result()
                capacities.append(result)
            except Exception as e:
                qpod = future_to_qpod[future]
                capacities.append({
                    'qpod': qpod,
                    'status': 'error',
                    'error': str(e),
                    'memory': 'N/A'
                })
    
    # Sort by qpod name
    capacities.sort(key=lambda x: x['qpod'])
    
    return jsonify(capacities)


# WebSocket event handlers for interactive terminal
@socketio.on('execute_command')
def handle_execute_command(data):
    """Execute arbitrary command in a shell"""
    session_id = request.sid
    command = data.get('command', '').strip()
    
    print(f"[DEBUG] Execute command: {command}")
    
    if not command:
        return
    
    def run_command():
        try:
            # Start a local shell
            import subprocess
            import pty
            import os
            import select
            import fcntl
            
            # Create a pseudo-terminal
            master, slave = pty.openpty()
            
            # Make master non-blocking
            flags = fcntl.fcntl(master, fcntl.F_GETFL)
            fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            
            # Start bash in interactive mode
            process = subprocess.Popen(
                ['/bin/bash', '-i'],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                preexec_fn=os.setsid
            )
            
            os.close(slave)
            
            # Wait a bit for bash to start
            import time
            time.sleep(0.1)
            
            # Send the command
            os.write(master, (command + '\n').encode())
            
            # Store session
            active_sessions[session_id] = {
                'process': process,
                'master': master
            }
            
            # Read output
            while True:
                try:
                    # Check if there's data to read (non-blocking)
                    try:
                        output_data = os.read(master, 4096).decode('utf-8', errors='replace')
                        if output_data:
                            socketio.emit('output', {'data': output_data}, room=session_id)
                    except OSError:
                        # No data available
                        pass
                    
                    # Check if process ended
                    poll_result = process.poll()
                    if poll_result is not None:
                        # Wait a bit more to get any remaining output
                        time.sleep(0.2)
                        try:
                            output_data = os.read(master, 4096).decode('utf-8', errors='replace')
                            if output_data:
                                socketio.emit('output', {'data': output_data}, room=session_id)
                        except:
                            pass
                        break
                    
                    time.sleep(0.05)
                    
                except Exception as e:
                    print(f"[ERROR] Read error: {e}")
                    break
            
            # Process ended
            exit_code = process.poll()
            socketio.emit('command_ended', {'exit_code': exit_code}, room=session_id)
            
            try:
                os.close(master)
            except:
                pass
            
            if session_id in active_sessions:
                del active_sessions[session_id]
                
        except Exception as e:
            print(f"[ERROR] Command execution error: {e}")
            import traceback
            traceback.print_exc()
            socketio.emit('error', {'error': str(e)}, room=session_id)
            if session_id in active_sessions:
                del active_sessions[session_id]
    
    # Run in background thread
    thread = threading.Thread(target=run_command)
    thread.daemon = True
    thread.start()


@socketio.on('connect_ssh')
def handle_connect_ssh(data):
    """Start a simple SSH connection to QPod (no build script)"""
    session_id = request.sid
    unix_id = data.get('unix_id')
    password = data.get('password')
    qpod = data.get('qpod')
    
    print(f"[DEBUG] Simple SSH connect for {unix_id}@{qpod}")
    
    if not all([unix_id, password, qpod]):
        emit('error', {'error': 'Missing required parameters'})
        return
    
    ssh_host = f"{qpod}.{SSH_DOMAIN}"
    
    def run_ssh_connect():
        try:
            # Create SSH client
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Connect
            socketio.emit('output', {'data': f'Connecting to {ssh_host}...\r\n'}, room=session_id)
            ssh.connect(ssh_host, username=unix_id, password=password, timeout=30)
            socketio.emit('output', {'data': 'Connected!\r\n\r\n'}, room=session_id)
            
            # Open interactive shell
            channel = ssh.invoke_shell()
            
            # Store session
            active_sessions[session_id] = {
                'ssh': ssh,
                'channel': channel
            }
            
            import time
            time.sleep(1)  # Wait for initial prompt
            
            # Read initial output (login messages, etc.)
            while channel.recv_ready():
                try:
                    output_data = channel.recv(1024).decode('utf-8', errors='replace')
                    socketio.emit('output', {'data': output_data}, room=session_id)
                except:
                    pass
            
            # Read output in a loop
            while True:
                if channel.recv_ready():
                    try:
                        output_data = channel.recv(1024).decode('utf-8', errors='replace')
                    except:
                        output_data = ''
                    if output_data:
                        socketio.emit('output', {'data': output_data}, room=session_id)
                
                if channel.exit_status_ready():
                    break
                
                time.sleep(0.05)
            
            # Session ended
            exit_status = channel.recv_exit_status()
            socketio.emit('output', {'data': f'\r\n\r\nConnection closed (exit code: {exit_status})\r\n'}, room=session_id)
            socketio.emit('session_ended', {'exit_code': exit_status}, room=session_id)
            
            channel.close()
            ssh.close()
            
            if session_id in active_sessions:
                del active_sessions[session_id]
                
        except Exception as e:
            print(f"[ERROR] SSH connection error: {e}")
            import traceback
            traceback.print_exc()
            socketio.emit('error', {'error': str(e)}, room=session_id)
            if session_id in active_sessions:
                try:
                    active_sessions[session_id]['channel'].close()
                    active_sessions[session_id]['ssh'].close()
                except:
                    pass
                del active_sessions[session_id]
    
    # Run in background thread
    thread = threading.Thread(target=run_ssh_connect)
    thread.daemon = True
    thread.start()


@socketio.on('monitor_deployment')
def handle_monitor_deployment(data):
    """Monitor deployment logs - stream to terminal AND update status every 30s (testing)"""
    session_id = request.sid
    unix_id = data.get('unix_id')
    password = data.get('password')
    qpod = data.get('qpod')
    build_name = data.get('build_name')
    log_path = data.get('log_path')
    
    print(f"[DEBUG] Starting deployment monitoring for {build_name} on {qpod}")
    
    if not all([unix_id, password, qpod, build_name, log_path]):
        emit('deployment_status', {'build_name': build_name, 'status': 'failed', 'error': 'Missing parameters'})
        return
    
    ssh_host = f"{qpod}.{SSH_DOMAIN}"
    
    def monitor_logs():
        """Background thread - streams logs to terminal AND sends progress updates"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            print(f"[DEBUG] Connecting to {ssh_host} for log monitoring...")
            ssh.connect(ssh_host, username=unix_id, password=password, timeout=30)
            
            channel = ssh.invoke_shell()
            
            import time
            time.sleep(1)
            
            # Clear initial output
            while channel.recv_ready():
                channel.recv(1024)
            
            # Run tail command to monitor logs
            command = f"tail -f {log_path}\n"
            channel.send(command)
            
            print(f"[DEBUG] Monitoring log: {log_path}")
            
            # Send initial message to terminal
            socketio.emit('output', {'data': f'\r\n📋 Streaming logs from {log_path}...\r\n'}, room=session_id)
            
            start_time = time.time()
            last_progress_update = time.time()
            timeout = 7200  # 2 hours
            
            recent_logs = []  # Store recent log lines for progress updates
            
            while True:
                if channel.recv_ready():
                    try:
                        output_data = channel.recv(4096).decode('utf-8', errors='replace')
                        
                        # Stream to terminal in real-time
                        socketio.emit('output', {'data': output_data}, room=session_id)
                        
                        # Store recent log lines
                        recent_logs.extend(output_data.split('\n'))
                        recent_logs = recent_logs[-10:]  # Keep last 10 lines
                        
                        # Check for success
                        if 'Deployment success' in output_data or 'deployment completed successfully' in output_data.lower():
                            print(f"[DEBUG] Deployment successful for {build_name}")
                            socketio.emit('deployment_status', {
                            'build_name': build_name,
                            'status': 'success'
                             }, room=session_id)
                            break
                        
                        # Check for failure
                        if 'Deployment failed' in output_data or 'deployment error' in output_data.lower() or 'ERROR:' in output_data:
                            print(f"[DEBUG] Deployment failed for {build_name}")
                            socketio.emit('deployment_status', {
                                'build_name': build_name,
                                'status': 'failed'
                            }, room=session_id)
                            break
                            
                    except Exception as e:
                        print(f"[ERROR] Error reading log data: {e}")
                
                # Send progress update every 30 seconds (TESTING - change to 120 for production)
                elapsed = time.time() - start_time
                time_since_last_update = time.time() - last_progress_update
                
                if time_since_last_update >= 30:  # 30 seconds for TESTING
                    minutes_elapsed = int(elapsed / 60)
    
                    # Filter and clean log lines
                    clean_lines = []
                for line in recent_logs[-5:]:  # Look at last 5 lines
                    line = line.strip()
                    # Skip empty, job IDs, timestamps, separators
                    if (line and 
                         not line.startswith('[') and  # Skip [1] [2] etc
                        not line.startswith('Job id') and
                        not line.startswith('+++') and
                        not line.startswith('===') and
                        not line.startswith('---') and
                        not 'Running' in line and
                    len(line) > 10):  # Skip very short lines
            # Take meaningful lines starting with ### or "Current time"
                        if line.startswith('###') or 'Current time' in line or 'Description:' in line:
                         clean_lines.append(line[:80])
    
    # Get last 3 meaningful lines
                         meaningful_lines = clean_lines[-3:] if clean_lines else ['Processing...']
                    log_snippet = '\n'.join(meaningful_lines)
                progress_text = f"⏱️ {minutes_elapsed}m\n{log_snippet}"
                    
                print(f"[DEBUG] Sending log_progress to {build_name}: {minutes_elapsed}m")
                    
                    # Send to status column
                socketio.emit('log_progress', {
                        'build_name': build_name,
                        'log_snippet': progress_text
                    }, room=session_id)
                    
                    # Also show in terminal
                socketio.emit('output', {
                        'data': f'\r\n⏱️  [{minutes_elapsed}m] Still deploying...\r\n'
                    }, room=session_id)
                    
                last_progress_update = time.time()
                
                # Timeout check
                if elapsed > timeout:
                    print(f"[DEBUG] Deployment timeout for {build_name}")
                    socketio.emit('deployment_status', {
                        'build_name': build_name,
                        'status': 'timeout'
                    }, room=session_id)
                    break
                
                # Check if user stopped
                if session_id not in active_sessions or active_sessions.get(session_id, {}).get('stopped'):
                    print(f"[DEBUG] Monitoring stopped by user for {build_name}")
                    break
                
                time.sleep(1)  # Check every second
            
            # Cleanup
            try:
                channel.send('\x03')  # Send Ctrl+C to stop tail
                time.sleep(0.5)
                channel.close()
            except:
                pass
            
            ssh.close()
            
            if session_id in active_sessions:
                del active_sessions[session_id]
            
        except Exception as e:
            print(f"[ERROR] Deployment monitoring error: {e}")
            import traceback
            traceback.print_exc()
            socketio.emit('deployment_status', {
                'build_name': build_name,
                'status': 'failed',
                'error': str(e)
            }, room=session_id)
    
    # Run in background thread - does NOT block UI
    thread = threading.Thread(target=monitor_logs)
    thread.daemon = True
    thread.start()


@socketio.on('stop_monitoring')
def handle_stop_monitoring(data):
    """Stop deployment monitoring"""
    session_id = request.sid
    if session_id in active_sessions:
        active_sessions[session_id]['stopped'] = True
        print(f"[DEBUG] Stopping monitoring for session {session_id}")


@socketio.on('start_session')
def handle_start_session(data):
    """Start an interactive SSH session"""
    session_id = request.sid
    unix_id = data.get('unix_id')
    password = data.get('password')
    qpod = data.get('qpod')
    build_name = data.get('build_name')
    profile_version = data.get('profile_version', DEFAULT_PROFILE_VERSION)
    
    print(f"[DEBUG] Starting session for {unix_id}@{qpod}")
    
    if not all([unix_id, password, qpod, build_name]):
        emit('error', {'error': 'Missing required parameters'})
        return
    
    ssh_host = f"{qpod}.{SSH_DOMAIN}"
    setup_profile = SETUP_PROFILE_BASE.format(version=profile_version)
    
    def run_ssh_session():
        try:
            # Create SSH client
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Connect
            socketio.emit('output', {'data': f'Connecting to {ssh_host}...\r\n'}, room=session_id)
            ssh.connect(ssh_host, username=unix_id, password=password, timeout=30)
            socketio.emit('output', {'data': 'Connected!\r\n\r\n'}, room=session_id)
            
            # Run ssh-add first
            socketio.emit('output', {'data': 'Running ssh-add...\r\n'}, room=session_id)
            channel = ssh.invoke_shell()
            channel.send('ssh-add\n')
            
            import time
            time.sleep(2)
            
            while channel.recv_ready():
                output_data = channel.recv(1024).decode('utf-8')
                socketio.emit('output', {'data': output_data}, room=session_id)
            
            socketio.emit('output', {'data': '\r\n'}, room=session_id)
            
            # Run the setup script
            command = f"{SETUP_SCRIPT} -n {setup_profile} -o __davinciVersion__={build_name}\n"
            socketio.emit('output', {'data': f'Executing: {command}'}, room=session_id)
            channel.send(command)
            
            # Store session
            active_sessions[session_id] = {
                'ssh': ssh,
                'channel': channel
            }
            
            # Read output in a loop
            while True:
                if channel.recv_ready():
                    try:
                        output_data = channel.recv(1024).decode('utf-8')
                    except UnicodeDecodeError:
                        # Handle binary/corrupted data
                        output_data = channel.recv(1024).decode('utf-8', errors='replace')
                    socketio.emit('output', {'data': output_data}, room=session_id)
                
                if channel.exit_status_ready():
                    break
                
                time.sleep(0.05)  # Reduced from 0.1 for faster response
            
            # Session ended
            exit_status = channel.recv_exit_status()
            socketio.emit('output', {'data': f'\r\n\r\nSession ended with exit code: {exit_status}\r\n'}, room=session_id)
            socketio.emit('session_ended', {'exit_code': exit_status}, room=session_id)
            
            channel.close()
            ssh.close()
            
            if session_id in active_sessions:
                del active_sessions[session_id]
                
        except Exception as e:
            print(f"[ERROR] SSH session error: {e}")
            import traceback
            traceback.print_exc()
            socketio.emit('error', {'error': str(e)}, room=session_id)
            if session_id in active_sessions:
                try:
                    active_sessions[session_id]['channel'].close()
                    active_sessions[session_id]['ssh'].close()
                except:
                    pass
                del active_sessions[session_id]
    
    # Run in background thread
    thread = threading.Thread(target=run_ssh_session)
    thread.daemon = True
    thread.start()


@socketio.on('input')
def handle_input(data):
    """Handle user input to the terminal"""
    session_id = request.sid
    user_input = data.get('data', '')
    
    if session_id in active_sessions:
        if 'channel' in active_sessions[session_id]:
            # SSH session
            channel = active_sessions[session_id]['channel']
            channel.send(user_input)
        elif 'master' in active_sessions[session_id]:
            # Command execution session
            import os
            master = active_sessions[session_id]['master']
            try:
                os.write(master, user_input.encode())
            except Exception as e:
                print(f"[ERROR] Failed to write to master: {e}")


@socketio.on('kill_session')
def handle_kill_session():
    """Handle Ctrl+C / kill request"""
    session_id = request.sid
    
    if session_id in active_sessions:
        try:
            channel = active_sessions[session_id]['channel']
            # Send Ctrl+C (ASCII 3)
            channel.send('\x03')
            socketio.emit('output', {'data': '\r\n^C\r\n'}, room=session_id)
        except Exception as e:
            print(f"[ERROR] Failed to send Ctrl+C: {e}")


@socketio.on('disconnect')
def handle_disconnect():
    """Clean up when client disconnects"""
    session_id = request.sid
    if session_id in active_sessions:
        try:
            active_sessions[session_id]['channel'].close()
            active_sessions[session_id]['ssh'].close()
        except:
            pass
        del active_sessions[session_id]

if __name__ == '__main__':
    from datetime import datetime
    current_year = datetime.now().year
    
    print("=" * 60)
    print("🚀 OVA Build Manager - Python Version")
    print(f"© HPE - {current_year}")
    print("=" * 60)
    print(f"Server running on: http://localhost:8080")
    print(f"OVA Repository: {OVA_BASE_URL}")
    print(f"Default QPods: {', '.join(QPODS)}")
    print(f"Default Profile Version: {DEFAULT_PROFILE_VERSION}")
    print("=" * 60)
    print("\n✅ Open your browser and go to: http://localhost:8080\n")
    
    socketio.run(app, debug=True, host='0.0.0.0', port=8080)
