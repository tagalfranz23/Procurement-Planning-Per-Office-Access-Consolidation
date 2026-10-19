"""Small standard-library Chrome DevTools transport for local browser checks."""
import base64
import json
import os
import socket
import struct
import time
from urllib.parse import urlparse


class CDP:
    def __init__(self, ws):
        parsed = urlparse(ws)
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET {parsed.path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        response = b''
        while b'\r\n\r\n' not in response:
            response += self.sock.recv(1)
        if b'HTTP/1.1 101 ' not in response:
            raise RuntimeError(response.decode())
        self.serial = 0
        self.events = []

    def exact(self, length):
        data = b''
        while len(data) < length:
            received = self.sock.recv(length - len(data))
            if not received:
                raise ConnectionError('Browser connection closed')
            data += received
        return data

    def send(self, body, opcode=1):
        data = body.encode() if isinstance(body, str) else body
        mask = os.urandom(4)
        length = len(data)
        header = bytes([0x80 | opcode, 0x80 | (length if length < 126 else 126 if length < 65536 else 127)])
        if length >= 126:
            header += struct.pack('!H' if length < 65536 else '!Q', length)
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def receive(self):
        first, second = self.exact(2)
        length = second & 127
        if length == 126:
            length = struct.unpack('!H', self.exact(2))[0]
        elif length == 127:
            length = struct.unpack('!Q', self.exact(8))[0]
        mask = self.exact(4) if second & 128 else None
        payload = self.exact(length)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if first & 15 == 9:
            self.send(payload, 10)
            return self.receive()
        return json.loads(payload)

    def call(self, method, params=None):
        self.serial += 1
        target = self.serial
        self.send(json.dumps({'id': target, 'method': method, 'params': params or {}}))
        while True:
            reply = self.receive()
            if reply.get('id') == target:
                if 'error' in reply:
                    raise RuntimeError(reply['error'])
                return reply.get('result', {})
            self.events.append(reply)

    def evaluate(self, expression):
        if 'await ' in expression:
            expression = '(async () => { ' + expression + ' })()'
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True})
        if 'exceptionDetails' in result:
            raise RuntimeError(result['exceptionDetails'])
        return result.get('result', {}).get('value')

    def wait_for(self, expression, timeout=30):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            try:
                if self.evaluate(expression):
                    return
            except RuntimeError:
                pass
            time.sleep(.15)
        raise RuntimeError(f'Wait failed: {expression}; URL={self.evaluate("location.href")}')
