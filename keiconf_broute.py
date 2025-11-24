"""
keilog設定モジュール - RL7023 Stick-D/IPS用Bルート設定
"""
import sys
import os

# keilogモジュールのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'keilog'))

from keilib.broute import WiSunRL7023, BrouteReader


def create_broute_reader(broute_id: str, broute_password: str, serial_port: str,
                        baudrate: int = 115200, timeout: int = 30,
                        properties: list = None, interval_seconds: int = 30) -> BrouteReader:
    """
    BrouteReaderインスタンスを作成する

    Args:
        broute_id: BルートID
        broute_password: Bルートパスワード
        serial_port: シリアルポート（例: /dev/ttyUSB0）
        baudrate: ボーレート（デフォルト: 115200）
        timeout: タイムアウト秒数（デフォルト: 30）
        properties: 取得するプロパティのリスト（デフォルト: D3,D7,E1,E7,E0,E3）
        interval_seconds: 取得間隔秒数（デフォルト: 30）

    Returns:
        BrouteReaderインスタンス
    """
    # デフォルトのプロパティ
    if properties is None:
        properties = ['D3', 'D7', 'E1', 'E7', 'E0', 'E3']

    # WiSunRL7023デバイスを初期化（RL7023 Stick-D/IPS用）
    wisundev = WiSunRL7023(
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
        record_que=None
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
