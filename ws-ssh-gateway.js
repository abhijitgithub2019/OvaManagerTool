/**
 * WebSocket-to-SSH Gateway for OVA Build Manager
 * 
 * This gateway allows the HTML/JavaScript version to make SSH connections
 * through WebSockets, bypassing browser limitations.
 * 
 * Usage:
 *   npm install ws ssh2
 *   node ws-ssh-gateway.js
 */

const WebSocket = require('ws');
const { Client } = require('ssh2');

const PORT = 8022;
const wss = new WebSocket.Server({ port: PORT });

console.log('='.repeat(60));
console.log('🔌 WebSocket-to-SSH Gateway');
console.log('='.repeat(60));
console.log(`Server running on: ws://localhost:${PORT}`);
console.log('Ready to accept SSH connections through WebSocket');
console.log('='.repeat(60));

wss.on('connection', (ws, req) => {
    const clientIp = req.socket.remoteAddress;
    console.log(`\n[${new Date().toISOString()}] New connection from ${clientIp}`);
    
    let sshClient = null;
    let sshStream = null;
    let sessionActive = false;
    
    ws.on('message', (message) => {
        try {
            const data = JSON.parse(message);
            
            if (data.action === 'connect') {
                console.log(`[${new Date().toISOString()}] SSH Connect: ${data.username}@${data.host}`);
                
                sshClient = new Client();
                
                sshClient.on('ready', () => {
                    console.log(`[${new Date().toISOString()}] SSH Connected successfully`);
                    sessionActive = true;
                    
                    ws.send(JSON.stringify({ 
                        type: 'connected',
                        message: 'SSH connection established'
                    }));
                    
                    // Request interactive shell
                    sshClient.shell({ 
                        term: 'xterm-256color',
                        cols: 80,
                        rows: 24
                    }, (err, stream) => {
                        if (err) {
                            console.error(`[${new Date().toISOString()}] Shell error:`, err.message);
                            ws.send(JSON.stringify({ 
                                type: 'error', 
                                message: 'Failed to start shell: ' + err.message 
                            }));
                            return;
                        }
                        
                        sshStream = stream;
                        
                        // Forward SSH output to WebSocket
                        stream.on('data', (data) => {
                            if (ws.readyState === WebSocket.OPEN) {
                                ws.send(JSON.stringify({ 
                                    type: 'output', 
                                    data: data.toString() 
                                }));
                            }
                        });
                        
                        stream.stderr.on('data', (data) => {
                            if (ws.readyState === WebSocket.OPEN) {
                                ws.send(JSON.stringify({ 
                                    type: 'output', 
                                    data: data.toString() 
                                }));
                            }
                        });
                        
                        stream.on('close', () => {
                            console.log(`[${new Date().toISOString()}] SSH Stream closed`);
                            sessionActive = false;
                            
                            if (ws.readyState === WebSocket.OPEN) {
                                ws.send(JSON.stringify({ 
                                    type: 'closed',
                                    message: 'SSH session ended'
                                }));
                            }
                            
                            if (sshClient) {
                                sshClient.end();
                            }
                        });
                        
                        stream.on('error', (err) => {
                            console.error(`[${new Date().toISOString()}] Stream error:`, err.message);
                        });
                    });
                });
                
                sshClient.on('error', (err) => {
                    console.error(`[${new Date().toISOString()}] SSH error:`, err.message);
                    sessionActive = false;
                    
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({ 
                            type: 'error', 
                            message: err.message 
                        }));
                    }
                });
                
                sshClient.on('close', () => {
                    console.log(`[${new Date().toISOString()}] SSH connection closed`);
                    sessionActive = false;
                });
                
                // Connect to SSH server
                try {
                    sshClient.connect({
                        host: data.host,
                        port: data.port || 22,
                        username: data.username,
                        password: data.password,
                        readyTimeout: 30000,
                        keepaliveInterval: 10000,
                        keepaliveCountMax: 3
                    });
                } catch (err) {
                    console.error(`[${new Date().toISOString()}] Connection error:`, err.message);
                    ws.send(JSON.stringify({ 
                        type: 'error', 
                        message: 'Connection failed: ' + err.message 
                    }));
                }
                
            } else if (data.action === 'input') {
                // Forward user input to SSH
                if (sshStream && sessionActive) {
                    sshStream.write(data.data);
                }
            } else if (data.action === 'resize') {
                // Handle terminal resize
                if (sshStream && sessionActive) {
                    sshStream.setWindow(data.rows || 24, data.cols || 80);
                }
            } else if (data.action === 'disconnect') {
                console.log(`[${new Date().toISOString()}] Client requested disconnect`);
                if (sshStream) {
                    sshStream.end();
                }
                if (sshClient) {
                    sshClient.end();
                }
                sessionActive = false;
            }
            
        } catch (err) {
            console.error(`[${new Date().toISOString()}] Message parsing error:`, err.message);
            ws.send(JSON.stringify({ 
                type: 'error', 
                message: 'Invalid message format' 
            }));
        }
    });
    
    ws.on('close', () => {
        console.log(`[${new Date().toISOString()}] WebSocket closed`);
        
        if (sshStream) {
            try {
                sshStream.end();
            } catch (err) {
                console.error('Error closing stream:', err.message);
            }
        }
        
        if (sshClient) {
            try {
                sshClient.end();
            } catch (err) {
                console.error('Error closing SSH client:', err.message);
            }
        }
        
        sessionActive = false;
    });
    
    ws.on('error', (err) => {
        console.error(`[${new Date().toISOString()}] WebSocket error:`, err.message);
    });
});

wss.on('error', (err) => {
    console.error('WebSocket Server error:', err.message);
});

// Graceful shutdown
process.on('SIGINT', () => {
    console.log('\n\nShutting down gracefully...');
    
    wss.clients.forEach((client) => {
        if (client.readyState === WebSocket.OPEN) {
            client.send(JSON.stringify({
                type: 'error',
                message: 'Server is shutting down'
            }));
            client.close();
        }
    });
    
    wss.close(() => {
        console.log('WebSocket server closed');
        process.exit(0);
    });
});

process.on('uncaughtException', (err) => {
    console.error('Uncaught exception:', err);
});

process.on('unhandledRejection', (reason, promise) => {
    console.error('Unhandled rejection at:', promise, 'reason:', reason);
});
