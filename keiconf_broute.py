"""
keilog設定モジュール - RL7023 Stick-D/IPS用Bルート設定
"""
import sys
import os
from logging import getLogger

import serial

# keilogモジュールのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'keilog'))

from keilib.broute import WiSunRL7023, BrouteReader

logger = getLogger(__name__)


class RemoteWiSunRL7023(WiSunRL7023):
    """socket:// と素のデバイスパスの両方を開ける WiSunRL7023。

    keilog 本体 (submodule, kjmat/keilog 127d414) の open() は
    serial.Serial(port=...) を直接呼ぶので socket:// を扱えない。
    **keilog は改造せず、ここで open() だけを差し替える。**

    serial.serial_for_url() はスキームの無い文字列をポート名として扱うので、
    ローカル USB 構成 (/dev/wisun) はこれまでと同じ経路で開く。
    切り替えは SERIAL_PORT の値だけ:

        /dev/wisun                  ローカル USB (従来どおり)
        socket://bridge:7001        ESP32 ブリッジ経由

    socket:// ではボーレート・DTR/RTS・フロー制御が相手に伝わらないが、
    シリアル条件はブリッジ側 (ESP32) で 115200 8N1 に固定しているので実害はない。
    """

    def open(self):
        self.ser = serial.serial_for_url(
            self.port,
            baudrate=self.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        logger.info('SKDevice open port={}, baud={}'.format(self.port, self.baud))
        return True


def create_broute_reader(broute_id: str, broute_password: str, serial_port: str,
                        baudrate: int = 115200, timeout: int = 30,
                        properties: list = None, interval_seconds: int = 30,
                        record_queue = None) -> BrouteReader:
    """
    BrouteReaderインスタンスを作成する

    Args:
        broute_id: BルートID
        broute_password: Bルートパスワード
        serial_port: シリアルポート。/dev/ttyUSB0 のようなデバイスパスか
            socket://bridge:7001 のような pyserial の URL
        baudrate: ボーレート（デフォルト: 115200）
        timeout: タイムアウト秒数（デフォルト: 30）※現在未使用
        properties: 取得するプロパティのリスト（デフォルト: D3,D7,E1,E7,E0,E3）
        interval_seconds: 取得間隔秒数（デフォルト: 30）
        record_queue: データを受け取るQueue（Noneの場合、データは破棄される）

    Returns:
        BrouteReaderインスタンス
    """
    # デフォルトのプロパティ
    if properties is None:
        properties = ['D3', 'D7', 'E1', 'E7', 'E0', 'E3']

    # WiSunRL7023デバイスを初期化（RL7023 Stick-D/IPS用）
    # socket:// と /dev/... の両方を開ける派生クラスを使う
    wisundev = RemoteWiSunRL7023(
        port=serial_port,
        baud=baudrate,
        type=WiSunRL7023.IPS  # RL7023 Stick-D/IPS用の指定
    )

    # リクエストリストを構築（keilogの形式に合わせる）
    requests = [
        {'epc': properties, 'cycle': interval_seconds}
    ]

    # BrouteReaderを初期化
    reader = BrouteReader(
        wisundev=wisundev,
        broute_id=broute_id,
        broute_pwd=broute_password,
        requests=requests,
        record_que=record_queue
    )

    return reader


def initialize_and_connect(reader: BrouteReader) -> bool:
    """
    BrouteReaderを初期化して接続する

    Args:
        reader: BrouteReaderインスタンス

    Returns:
        接続成功時True、失敗時False
    """
    try:
        # スマートメーターに接続
        reader.start()
        return True
    except Exception as e:
        print(f"接続エラー: {e}")
        return False
