#!/usr/bin/env python3
"""
スマートメーターデータロガー
RL7023 Stick-D/IPS + keilog を使用してBルートデータを取得し、CSVまたはInfluxDBに保存
"""
import os
import sys
import time
import csv
import logging
import queue
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, Optional

import yaml
from dotenv import load_dotenv

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from keiconf_broute import create_broute_reader, initialize_and_connect

# InfluxDB v2用のクライアント（オプション）
try:
    from influxdb_client import InfluxDBClient, Point
    from influxdb_client.client.write_api import SYNCHRONOUS
    INFLUXDB_AVAILABLE = True
except ImportError:
    INFLUXDB_AVAILABLE = False


class SmartMeterLogger:
    """スマートメーターデータロガー"""

    def __init__(self, config_path: str = '/app/config/settings.yml'):
        """初期化"""
        # 環境変数を読み込み
        load_dotenv()

        # 設定ファイルを読み込み
        self.config = self._load_config(config_path)

        # ロガーを初期化
        self.logger = self._setup_logger()

        # InfluxDBクライアント
        self.influx_client = None
        self.write_api = None

        # BrouteReader and data queue
        self.reader = None
        self.data_queue = queue.Queue(50)

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """設定ファイルを読み込む"""
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 環境変数で上書き
        if os.getenv('BROUTE_ID'):
            config['broute']['id'] = os.getenv('BROUTE_ID')
        if os.getenv('BROUTE_PASSWORD'):
            config['broute']['password'] = os.getenv('BROUTE_PASSWORD')
        if os.getenv('SERIAL_PORT'):
            config['serial']['port'] = os.getenv('SERIAL_PORT')
        if os.getenv('INFLUXDB_URL'):
            config['influxdb']['url'] = os.getenv('INFLUXDB_URL')
        if os.getenv('INFLUXDB_TOKEN'):
            config['influxdb']['token'] = os.getenv('INFLUXDB_TOKEN')
        if os.getenv('INFLUXDB_ORG'):
            config['influxdb']['org'] = os.getenv('INFLUXDB_ORG')
        if os.getenv('INFLUXDB_BUCKET'):
            config['influxdb']['bucket'] = os.getenv('INFLUXDB_BUCKET')

        return config

    def _setup_logger(self) -> logging.Logger:
        """ロガーをセットアップ"""
        logger = logging.getLogger('smartmeter_logger')
        logger.setLevel(getattr(logging, self.config['logging']['level']))

        # ログディレクトリを作成
        log_file = Path(self.config['logging']['file'])
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # ファイルハンドラー（ローテーション）
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=self.config['logging']['max_bytes'],
            backupCount=self.config['logging']['backup_count']
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)

        # コンソールハンドラー（エラーのみ）
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.ERROR)
        console_formatter = logging.Formatter('%(levelname)s: %(message)s')
        console_handler.setFormatter(console_formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    def _init_influxdb(self) -> bool:
        """InfluxDB接続を初期化"""
        if not self.config['influxdb']['enabled']:
            self.logger.info("InfluxDB直接書き込みは無効です（CSVモード）")
            return False

        if not INFLUXDB_AVAILABLE:
            self.logger.error("influxdb-clientがインストールされていません")
            return False

        try:
            self.influx_client = InfluxDBClient(
                url=self.config['influxdb']['url'],
                token=self.config['influxdb']['token'],
                org=self.config['influxdb']['org']
            )
            self.write_api = self.influx_client.write_api(write_options=SYNCHRONOUS)
            self.logger.info("InfluxDB接続成功")
            return True
        except Exception as e:
            self.logger.error(f"InfluxDB接続エラー: {e}")
            return False

    def _init_broute_reader(self) -> bool:
        """BrouteReaderを初期化"""
        try:
            self.reader = create_broute_reader(
                broute_id=self.config['broute']['id'],
                broute_password=self.config['broute']['password'],
                serial_port=self.config['serial']['port'],
                baudrate=self.config['serial']['baudrate'],
                timeout=self.config['serial']['timeout'],
                properties=self.config['acquisition']['properties'],
                interval_seconds=self.config['acquisition']['interval_seconds'],
                record_queue=self.data_queue
            )

            if initialize_and_connect(self.reader):
                self.logger.info("スマートメーター接続成功")
                return True
            else:
                self.logger.error("スマートメーター接続失敗")
                return False

        except Exception as e:
            self.logger.error(f"BrouteReader初期化エラー: {e}")
            return False

    def _get_csv_filepath(self) -> Path:
        """CSV出力ファイルパスを取得"""
        output_dir = Path(self.config['csv']['output_dir'])
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = datetime.now().strftime(self.config['csv']['filename_format'])
        return output_dir / filename

    def _write_to_csv(self, data: Dict[str, Any]) -> None:
        """CSVファイルに書き込み"""
        if not self.config['csv']['enabled']:
            return

        csv_file = self._get_csv_filepath()
        file_exists = csv_file.exists()

        try:
            with open(csv_file, 'a', newline='', encoding='utf-8') as f:
                fieldnames = ['timestamp'] + list(data.keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                # ヘッダーを書き込み（ファイルが新規の場合）
                if not file_exists:
                    writer.writeheader()

                # データ行を書き込み
                row = {'timestamp': datetime.now().isoformat()}
                row.update(data)
                writer.writerow(row)

            self.logger.debug(f"CSVに書き込み: {csv_file}")

        except Exception as e:
            self.logger.error(f"CSV書き込みエラー: {e}")

    def _write_to_influxdb(self, data: Dict[str, Any]) -> None:
        """InfluxDBに書き込み"""
        if not self.config['influxdb']['enabled'] or not self.write_api:
            return

        try:
            point = Point(self.config['influxdb']['measurement'])

            # タグを追加
            for tag_key, tag_value in self.config['influxdb']['tags'].items():
                point = point.tag(tag_key, tag_value)

            # フィールドを追加
            for field_key, field_value in data.items():
                if isinstance(field_value, (int, float)):
                    point = point.field(field_key, field_value)
                else:
                    point = point.field(field_key, str(field_value))

            # タイムスタンプを追加
            point = point.time(datetime.utcnow())

            # 書き込み
            self.write_api.write(
                bucket=self.config['influxdb']['bucket'],
                record=point
            )

            self.logger.debug("InfluxDBに書き込み成功")

        except Exception as e:
            self.logger.error(f"InfluxDB書き込みエラー: {e}")

    def _parse_queue_data(self, queue_data: list) -> Optional[Dict[str, Any]]:
        """
        Queueから取得したデータを解析して整形

        Args:
            queue_data: ['BR', epc, value, status] 形式のデータ

        Returns:
            整形されたデータ辞書、またはNone
        """
        if not queue_data or len(queue_data) < 3:
            return None

        source, epc, value, *rest = queue_data

        if source != 'BR':
            return None

        parsed = {}

        try:
            # 瞬時電力 (E7) - W単位
            if epc == 'E7':
                parsed['instant_power_w'] = int(value)

            # 積算電力量（正方向）(E0)
            elif epc == 'E0':
                parsed['energy_total_kwh'] = float(value)

            # 積算電力量（逆方向）(E3)
            elif epc == 'E3':
                parsed['energy_reverse_kwh'] = float(value)

            # 係数 (D3)
            elif epc == 'D3':
                parsed['coefficient'] = int(value)

            # 積算電力量有効桁数 (D7)
            elif epc == 'D7':
                parsed['effective_digits'] = int(value)

            # 積算電力量単位 (E1)
            elif epc == 'E1':
                parsed['unit'] = int(value)

            # 瞬時電流 R相 (E8R)
            elif epc == 'E8R':
                parsed['instant_current_r'] = float(value)

            # 瞬時電流 T相 (E8T)
            elif epc == 'E8T':
                parsed['instant_current_t'] = float(value)

        except Exception as e:
            self.logger.error(f"データ解析エラー: {e}, data={queue_data}")
            return None

        return parsed if parsed else None

    def run(self) -> None:
        """メインループ"""
        self.logger.info("スマートメーターロガー起動")

        # InfluxDBを初期化（有効な場合）
        self._init_influxdb()

        # BrouteReaderを初期化
        if not self._init_broute_reader():
            self.logger.error("初期化失敗。終了します。")
            sys.exit(1)

        self.logger.info("データ取得開始")

        try:
            while True:
                try:
                    # Queueからデータを取得（タイムアウト付き）
                    try:
                        queue_data = self.data_queue.get(timeout=5)
                    except queue.Empty:
                        continue

                    # データを解析
                    parsed_data = self._parse_queue_data(queue_data)

                    if parsed_data:
                        self.logger.info(f"データ取得: {parsed_data}")

                        # CSVに書き込み
                        self._write_to_csv(parsed_data)

                        # InfluxDBに書き込み（有効な場合）
                        self._write_to_influxdb(parsed_data)
                    else:
                        self.logger.debug(f"Unknown data from queue: {queue_data}")

                except Exception as e:
                    self.logger.error(f"データ処理エラー: {e}")

        except KeyboardInterrupt:
            self.logger.info("終了シグナル受信")
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        """クリーンアップ処理"""
        self.logger.info("クリーンアップ中...")

        if self.reader:
            try:
                self.reader.stop()
            except Exception as e:
                self.logger.error(f"Reader停止エラー: {e}")

        if self.influx_client:
            try:
                self.influx_client.close()
            except Exception as e:
                self.logger.error(f"InfluxDB接続クローズエラー: {e}")

        self.logger.info("終了")


def main():
    """エントリーポイント"""
    logger = SmartMeterLogger()
    logger.run()


if __name__ == '__main__':
    main()
