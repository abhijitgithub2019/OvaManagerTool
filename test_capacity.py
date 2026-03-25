#!/usr/bin/env python3
"""Test script to check if capacity checking works"""
import paramiko

def test_capacity(qpod, unix_id, password):
    ssh_host = f"{qpod}.englab.juniper.net"
    print(f"Connecting to {ssh_host}...")
    
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ssh_host, username=unix_id, password=password, timeout=15)
        
        print("Connected! Running command...")
        stdin, stdout, stderr = ssh.exec_command('vmm capacity -g vmm-default')
        
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        
        print("Output:")
        print(output)
        
        if error:
            print("Error:")
            print(error)
        
        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 4:
        print("Usage: python3 test_capacity.py <qpod> <unix_id> <password>")
        print("Example: python3 test_capacity.py q-pod30-vmm myuser mypassword")
    else:
        test_capacity(sys.argv[1], sys.argv[2], sys.argv[3])
