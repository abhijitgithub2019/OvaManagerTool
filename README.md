# OVA Build Manager - Python Version with QPod Capacity Check

Python-based OVA Build Manager that checks QPod capacities and lets you choose the best one for deployment.

## 🎯 New Features

✅ **QPod Capacity Checking** - Check memory on all QPods before deploying  
✅ **Multi-QPod Support** - Choose from q-pod30, q-pod32, q-pod36, q-pod38  
✅ **Smart Selection** - See which QPod has the most available capacity  
✅ **Auto EPIC Detection** - Fetches versions from mistsys/epic-ui in images.txt  
✅ **Date Display** - Shows build dates in DD-MMM-YYYY HH:MM format  

## Installation

### Step 1: Install Python Dependencies
```bash
pip3 install Flask requests beautifulsoup4 paramiko
```

Or use the requirements file:
```bash
pip3 install -r requirements.txt
```

## Usage

### Start the Server
```bash
python3 app.py
```

Output:
```
============================================================
🚀 OVA Build Manager - Python Version
============================================================
Server running on: http://localhost:8080
OVA Repository: http://storage1.qnc.kanlab.jnpr.net/ova/
Available QPods: q-pod30-vmm, q-pod32-vmm, q-pod36-vmm, q-pod38-vmm
============================================================
✅ Open your browser and go to: http://localhost:8080
```

### Using the Application

1. **Open Browser**: http://localhost:8080

2. **Enter Credentials**:
   - Unix ID: your username
   - Password: your SSH password

3. **Check QPod Capacities**:
   - Click "🔍 Check QPod Capacities"
   - The app will SSH to each QPod and run `vmm capacity -g vmm-default`
   - View memory capacity for each QPod

4. **Select QPod**:
   - Choose the QPod with the best available capacity from the dropdown

5. **Select Build**:
   - Browse the builds table (shows Build Number, Date, EPIC Version)
   - Click "Create Build" for your desired build

6. **Copy Command**:
   - The SSH command will be generated for the selected QPod
   - Click "📋 Copy Command"
   - Paste into your terminal

## How It Works

### Capacity Check Flow
```
User clicks "Check QPod Capacities"
    ↓
For each QPod (30, 32, 36, 38):
    SSH → Run: vmm capacity -g vmm-default → Parse output
    ↓
Display memory capacity for each QPod
    ↓
User selects QPod with best capacity
```

### Build Deployment Flow
```
User selects build → Chooses QPod → Clicks "Create Build"
    ↓
Generates command:
    ssh user@q-pod30-vmm.englab.juniper.net
    /homes/jtsai/full_setup.sh -n ... -o __davinciVersion__=develop.XXXXX
    ↓
User copies and executes in terminal
```

## Testing Capacity Check

Use the included test script to verify capacity checking works:

```bash
python3 test_capacity.py q-pod30-vmm your_unix_id your_password
```

This will connect to the QPod and show the capacity output.

## Files

```
ova-build-manager-python/
├── app.py                # Main application
├── requirements.txt      # Python dependencies  
├── test_capacity.py      # Test script for capacity checking
└── README.md            # This file
```

## License

MIT
