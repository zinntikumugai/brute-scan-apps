"""RemoteWiSunRL7023 が socket:// と素のデバイスパスの**両方**を開けること。

実機（RL7023）もブリッジも無しで回る。
  uv run --with pytest --with pyserial pytest tests/

ここが壊れると、remote 構成（socket://bridge:7001）かローカル USB 構成
（/dev/wisun）のどちらかが黙って動かなくなる。
"""
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from keiconf_broute import RemoteWiSunRL7023  # noqa: E402
from keilib.broute import WiSunRL7023  # noqa: E402


def _reply(line: bytes) -> bytes:
    """RL7023 のふり: コマンドをエコーして応答と OK を返す。"""
    out = line + b'\r\n'
    if line.startswith(b'SKVER'):
        out += b'EVER 1.2.8\r\n'
    return out + b'OK\r\n'


def test_plain_device_path_opens_like_before():
    """素のデバイスパスは従来どおり serial.Serial で開く（USB 構成の回帰）。

    PTY を疑似デバイスにする。**読み書きはここでは試さない**:
    PTY のエコーと噛み合って無限ループになりやすく、open の後の経路は
    socket:// 側のテストで通っている（keilog から見れば同じ Serial オブジェクト）。
    ここで守りたいのは「素のパスが URL として解釈されてしまわないこと」。
    """
    master, slave = os.openpty()
    try:
        dev = RemoteWiSunRL7023(port=os.ttyname(slave), baud=115200,
                                type=WiSunRL7023.IPS)
        assert dev.open() is True
        # 旧実装（serial.Serial）と同じクラスで開いていること。
        # socket:// の場合は serial.urlhandler.* になるので区別できる。
        assert type(dev.ser).__module__ == 'serial.serialposix'
        assert dev.ser.is_open
        assert dev.ser.baudrate == 115200
        dev.ser.close()
    finally:
        os.close(master)
        os.close(slave)


def test_socket_url_opens():
    """socket://host:port を開けること（ブリッジ経由の remote 構成）。"""
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def responder():
        conn, _ = srv.accept()
        conn.settimeout(0.2)
        buf = b''
        while not stop.is_set():
            try:
                chunk = conn.recv(256)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b'\r\n' in buf:
                line, buf = buf.split(b'\r\n', 1)
                conn.sendall(_reply(line))
        conn.close()

    t = threading.Thread(target=responder, daemon=True)
    t.start()
    try:
        dev = RemoteWiSunRL7023(port=f'socket://127.0.0.1:{port}', baud=115200,
                                type=WiSunRL7023.IPS)
        assert dev.open() is True
        assert dev.reset() is True

        dev.ser.write(b'SKVER\r\n')
        got, end = b'', time.time() + 3
        while time.time() < end and b'EVER' not in got:
            got += dev.ser.readline()
        assert b'EVER 1.2.8' in got
        dev.close()
    finally:
        stop.set()
        srv.close()
