class HyperWebSocket {
    constructor(path, onMessage) {
        this.path = path;
        this.onMessage = onMessage;
        this.socket = null;
        this.reconnectDelay = 3000;
        this.isConnected = false;
        
        // Use relative WSS/WS path based on current location
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.url = `${protocol}//${window.location.host}${path}`;
    }

    connect() {
        console.log(`[WS] Connecting to ${this.url}`);
        this.socket = new WebSocket(this.url);

        this.socket.onopen = () => {
            console.log(`[WS] Connected to ${this.path}`);
            this.isConnected = true;
            this._updateGlobalStatus();
        };

        this.socket.onmessage = (event) => {
            if (this.onMessage) {
                this.onMessage(event.data);
            }
        };

        this.socket.onclose = () => {
            console.log(`[WS] Disconnected from ${this.path}. Reconnecting in ${this.reconnectDelay}ms...`);
            this.isConnected = false;
            this._updateGlobalStatus();
            setTimeout(() => this.connect(), this.reconnectDelay);
        };

        this.socket.onerror = (err) => {
            console.error(`[WS] Error on ${this.path}:`, err);
            this.socket.close();
        };
    }

    disconnect() {
        if (this.socket) {
            this.socket.close();
        }
    }

    send(data) {
        if (this.isConnected && this.socket) {
            this.socket.send(data);
        }
    }

    _updateGlobalStatus() {
        // Very simple global status update based on connection states
        const dot = document.getElementById('socket-status');
        const text = document.getElementById('socket-text');
        if (dot && text) {
            // We assume if one WS connects, system is "Online"
            if (this.isConnected) {
                dot.classList.add('connected');
                text.textContent = 'Online';
                text.style.color = 'var(--success)';
            } else {
                dot.classList.remove('connected');
                text.textContent = 'Offline';
                text.style.color = 'var(--danger)';
            }
        }
    }
}

window.HyperWebSocket = HyperWebSocket;
