# スマートメーター Bルート データロガー

RL7023 Stick-D/IPS + keilog を使用してスマートメーターからBルートデータを取得し、InfluxDB v2に保存するシステムです。

## 2 つの接続構成

RL7023 の繋ぎ方が 2 通りあり、**同じコード・同じイメージ**でどちらでも動きます。
切り替えるのは `.env` の `SERIAL_PORT` と、重ねる compose ファイルだけです。

| 構成 | SERIAL_PORT | 起動コマンド |
|---|---|---|
| **ローカル USB**（このホストに RL7023 を直挿し） | `/dev/wisun` | `docker compose -f docker-compose.yml -f docker-compose.usb.yml up -d` |
| **remote**（ESP32 ブリッジ経由で離れた場所の RL7023 を使う） | `socket://bridge:7001` | `docker compose -f docker-compose.yml -f docker-compose.remote.yml up -d` |

> **USB 構成でもコマンドが変わりました。** `docker-compose.usb.yml` を重ねてください。
> compose の `devices` は override で追加はできても削除できないため、
> devices 無しを既定にして USB 構成で足す向きにしています。

### 既存の USB 構成からの移行

**`.env` の `SERIAL_PORT` の意味が変わりました。** 以前は「ホスト側のデバイスパス」で、
コンテナ内では `/dev/wisun` 固定でした。いまは「アプリが開く先」そのもので、
ホスト側のパスは `SERIAL_DEVICE` に分かれています。

```diff
-SERIAL_PORT=/dev/serial/by-id/usb-ROHM_BP35A1_XXXXXXXX-if00
+SERIAL_PORT=/dev/wisun
+SERIAL_DEVICE=/dev/serial/by-id/usb-ROHM_BP35A1_XXXXXXXX-if00
```

更新手順（USB 構成のホストで）:

```bash
git pull                       # compose ファイル自体が変わっているので image だけでは足りない
vi .env                        # 上の 2 行に直す
docker compose pull
docker compose -f docker-compose.yml -f docker-compose.usb.yml up -d
```

`SERIAL_DEVICE` を書き忘れた場合は `required variable SERIAL_DEVICE is missing a value`
で**起動せずに止まります**（デバイスの無いコンテナが黙って上がらないように `:?` を付けてある）。

remote 構成では、ESP32 ブリッジ側（WiSUN-ESP32-relay）の compose を先に起動して
`smartmeter_network` を作っておきます。logger はそのネットワークに参加し、
`socket://bridge:7001` で離れた RL7023 と話します。

```
smartmeter_logger ──socket://bridge:7001──> bridge (Go) ──TLS──> ESP32 ──USB──> RL7023
```

**keilog（サブモジュール）は 1 行も変えていません**（`127d414` のまま）。
`socket://` 対応は `keiconf_broute.py` の `RemoteWiSunRL7023` が
`open()` だけを `serial.serial_for_url()` に差し替えて実現しています。

## 構成

- **smartmeter_logger**: Pythonアプリケーション（スマートメーターからデータ取得）
- **telegraf**: CSVファイルをInfluxDB v2に転送
- **InfluxDB v2**: 外部サーバー（別途用意が必要）
- **keilog**: Gitサブモジュールとして管理
- **UV**: Pythonパッケージマネージャー

## 取得データ

- **瞬時電力** (E7): 現在の消費電力 [W]
- **積算電力量（正方向）** (E0): 買電の積算値 [kWh]
- **積算電力量（逆方向）** (E3): 売電の積算値 [kWh]
- その他: 係数(D3), 単位(D7), 有効桁数(E1)

## 前提条件

### ハードウェア
- **Wi-SUNモジュール**: RL7023 Stick-D/IPS
- **ホストPC**: Linux（Dockerが動作する環境）

### ソフトウェア
- Git
- Docker
- Docker Compose
- 外部InfluxDB v2サーバー

### Bルート認証情報
電力会社から以下の情報を取得してください：
- Bルート ID
- Bルート パスワード

## セットアップ手順

### 1. リポジトリのクローン

```bash
# リポジトリをクローン
git clone https://github.com/zinntikumugai/brute-scan-apps.git
cd brute-scan-apps

# サブモジュール（keilog）を初期化・取得
git submodule init
git submodule update
```

または、一度にクローン：

```bash
git clone --recursive https://github.com/zinntikumugai/brute-scan-apps.git
cd brute-scan-apps
```

### 2. デバイスの接続確認

RL7023 Stick-D/IPSをUSBポートに接続し、デバイスパスを確認します。

```bash
ls -l /dev/serial/by-id/
```

例: `/dev/serial/by-id/usb-ROHM_BP35A1_XXXXXXXX-if00`

### 3. 環境変数の設定

`.env.example`をコピーして`.env`ファイルを作成します。

```bash
cp .env.example .env
```

`.env`ファイルを編集して、以下の情報を設定します：

```env
# Bルート認証情報
BROUTE_ID=your_broute_id_here
BROUTE_PASSWORD=your_broute_password_here

# シリアルポート（下の 2 通りのどちらか）
#  ローカル USB 構成: コンテナ内のパスを書く。実デバイスは SERIAL_DEVICE
SERIAL_PORT=/dev/wisun
SERIAL_DEVICE=/dev/serial/by-id/usb-ROHM_BP35A1_XXXXXXXX-if00
#  remote 構成（ESP32 ブリッジ経由）: SERIAL_DEVICE は不要
# SERIAL_PORT=socket://bridge:7001

# InfluxDB v2設定
INFLUXDB_URL=http://your-influxdb-host:8086
INFLUXDB_TOKEN=your_influxdb_token_here
INFLUXDB_ORG=your_organization_name
INFLUXDB_BUCKET=power
```

### 4. 設定ファイルの調整（オプション）

`config/settings.yml`でデータ取得間隔やログレベルなどを調整できます。

```yaml
# データ取得間隔（秒）
acquisition:
  interval_seconds: 30

# ログレベル
logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR
```

### 5. InfluxDB v2の準備

外部InfluxDB v2サーバーで以下を準備します：

1. **Organization**を作成（または既存のものを使用）
2. **Bucket**を作成（例: `power`）
3. **APIトークン**を生成（書き込み権限が必要）

InfluxDB CLIでの例：

```bash
# Bucketを作成
influx bucket create -n power -o your_org

# APIトークンを作成
influx auth create \
  --org your_org \
  --read-bucket power \
  --write-bucket power
```

## 起動方法

### Docker Composeで起動

**構成に応じて重ねるファイルが変わります**（上の「2 つの接続構成」を参照）。

```bash
# ローカル USB 構成
docker compose -f docker-compose.yml -f docker-compose.usb.yml up -d --build

# remote 構成（ESP32 ブリッジ経由。先にブリッジ側の compose を起動しておく）
docker compose -f docker-compose.yml -f docker-compose.remote.yml up -d --build

# ログを確認
docker compose logs -f smartmeter_logger
docker compose logs -f telegraf
```

### reader スレッドの自動復旧

TCP 切断や USB 抜けが起きると keilog の reader スレッドだけが終了し、
**プロセスは生きたままデータが止まります**（Docker の restart policy も効きません）。
`smartmeter_logger.py` は毎秒 reader の生死を見て、死んでいたら
古いソケットを閉じ、受信キューを捨ててから作り直します
（1 → 2 → 4 … 最大 60 秒のバックオフ）。ログにはこう出ます:

```
ERROR - BrouteReaderスレッドが停止している。再生成する (通算 N 回目)
INFO  - BrouteReaderを再生成した
```

この行が延々と増え続ける場合は、接続先（USB デバイスかブリッジ）が落ちています。

### テスト

実機もブリッジも要らないテストがあります。

```bash
uv run --with pytest --with pyserial pytest tests/
```

### 初回起動時の注意

- スマートメーターとの接続には数分かかる場合があります
- `/app/logs/smartmeter_logger.log`でログを確認してください

```bash
docker compose exec smartmeter_logger tail -f /app/logs/smartmeter_logger.log
```

## ローカル開発環境（UVを使用）

### UVのインストール

```bash
# UVをインストール（推奨方法）
curl -LsSf https://astral.sh/uv/install.sh | sh

# または pipx を使用
pipx install uv
```

### 依存関係のインストール

```bash
# プロジェクトディレクトリで実行
uv pip install -e .

# 開発用依存関係も含める場合
uv pip install -e ".[dev]"

# または仮想環境を作成してインストール
uv venv
source .venv/bin/activate  # Linuxの場合
uv pip install -e .
```

### ローカルでの実行

```bash
# 環境変数を設定
export BROUTE_ID=your_id
export BROUTE_PASSWORD=your_password
export SERIAL_PORT=/dev/serial/by-id/usb-ROHM_BP35A1_XXXXXXXX-if00

# スクリプトを実行
python src/smartmeter_logger.py
```

## データフロー

```
RL7023 Stick-D/IPS
  ↓
[smartmeter_logger]
  ↓ CSV出力
logs/YYYYMMDD-smartmeter.csv
  ↓
[telegraf]
  ↓
外部 InfluxDB v2
```

## データ確認方法

### CSVファイルの確認

```bash
# 最新のCSVファイルを確認
docker compose exec smartmeter_logger tail /app/logs/*.csv
```

CSVフォーマット例（Long Format - 1行1プロパティ）：
```csv
timestamp,unitid,epc,dataid,value
2025-11-24T12:00:00.123456,smartmeter01,E7,,1234
2025-11-24T12:00:00.234567,smartmeter01,E0,,5678.9
2025-11-24T12:00:00.345678,smartmeter01,D3,,1
```

各プロパティが個別の行として記録されます：
- `timestamp`: データ取得時刻（ISO8601形式）
- `unitid`: メーター識別ID（config/settings.ymlで設定）
- `epc`: EPCコード（E7=瞬時電力, E0=積算電力量など）
- `dataid`: データID（通常は空、将来の拡張用）
- `value`: 測定値

### InfluxDBでの確認

InfluxDB CLIでクエリ：

```bash
influx query 'from(bucket: "power")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "smartmeter_power")
  |> limit(n: 10)'
```

またはFlux言語で：

```flux
from(bucket: "power")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "smartmeter_power")
  |> filter(fn: (r) => r.epc == "E7")  # 瞬時電力のみ
  |> filter(fn: (r) => r._field == "value")
```

## デバッグモード

### DEBUG環境変数を使用

デバッグモードを有効にすると、すべてのログがコンソールに出力されます（keilog互換）：

```bash
# docker-compose.ymlに追加
services:
  smartmeter_logger:
    environment:
      - DEBUG=1  # デバッグモード有効
```

または、一時的に有効化：

```bash
docker compose run --rm -e DEBUG=1 smartmeter_logger
```

### ログレベルの動的切り替え

実行中のコンテナのログレベルを切り替えることができます（SIGUSR1シグナル）：

```bash
# コンテナ内のプロセスIDを確認
docker compose exec smartmeter_logger ps aux

# ログレベルを切り替え（DEBUG ⇔ INFO）
docker compose exec smartmeter_logger kill -USR1 <PID>
```

例：
```bash
docker compose exec smartmeter_logger kill -USR1 1
```

## グレースフルシャットダウン

コンテナの再起動や停止時、データ破損を防ぐためグレースフルシャットダウンを実装しています：

- BrouteReaderスレッドの安全な停止（keilog内部処理）
- シリアルポート接続のクリーンアップ
- InfluxDB接続のクローズ
- 最大30秒のシャットダウン猶予期間（`stop_grace_period`）

```bash
# 安全な再起動
docker compose restart smartmeter_logger

# 安全な停止
docker compose stop smartmeter_logger
```

ログで確認できる正常なシャットダウン手順：
```
INFO: SIGTERMシグナル受信 - グレースフルシャットダウン開始
INFO: クリーンアップ中...
INFO: BrouteReaderスレッド停止中...
INFO: BrouteReaderスレッド停止完了
INFO: InfluxDB接続クローズ完了
INFO: 終了
```

## トラブルシューティング

### サブモジュールが空の場合

```bash
# サブモジュールを更新
git submodule update --init --recursive
```

### デバイスが認識されない

```bash
# デバイスの確認
ls -l /dev/serial/by-id/
lsusb

# 権限の確認
ls -l /dev/ttyUSB0

# ユーザーをdialoutグループに追加
sudo usermod -a -G dialout $USER
```

### 接続がタイムアウトする

- Bルート ID/パスワードが正しいか確認
- Wi-SUNモジュールがスマートメーター近くにあるか確認
- スマートメーターのBルート機能が有効か確認（電力会社に確認）

### CSVファイルが作成されない

```bash
# ログを確認
docker compose logs smartmeter_logger

# コンテナ内でディレクトリを確認
docker compose exec smartmeter_logger ls -la /app/logs/
```

### Telegrafがデータを送信しない

```bash
# Telegrafログを確認
docker compose logs telegraf

# Telegraf設定をテスト
docker compose exec telegraf telegraf --config /etc/telegraf/telegraf.conf --test
```

## ディレクトリ構造

```
.
├── docker-compose.yml        # Docker Compose設定
├── Dockerfile                # Pythonアプリ用Dockerfile
├── pyproject.toml            # Python依存関係（UV管理）
├── .env                      # 環境変数（要作成）
├── .env.example              # 環境変数テンプレート
├── .gitmodules               # Gitサブモジュール設定
├── config/
│   └── settings.yml          # アプリ設定ファイル
├── src/
│   └── smartmeter_logger.py  # メインアプリケーション
├── keilog/                   # keilog（Gitサブモジュール）
├── keiconf_broute.py         # keilog設定モジュール
├── telegraf.conf             # Telegraf設定
├── logs/                     # ログ出力ディレクトリ
│   ├── YYYYMMDD-smartmeter.csv
│   └── smartmeter_logger.log
└── README.md                 # このファイル
```

## 停止方法

```bash
# コンテナを停止
docker compose down

# コンテナとボリュームを削除
docker compose down -v
```

## 設定のカスタマイズ

### データ取得間隔の変更

`config/settings.yml`:
```yaml
acquisition:
  interval_seconds: 60  # 30秒 → 60秒に変更
```

### InfluxDBへの直接書き込み（telegrafを使わない場合）

`config/settings.yml`:
```yaml
csv:
  enabled: false  # CSV出力を無効化

influxdb:
  enabled: true   # InfluxDB直接書き込みを有効化
```

この場合、telegrafコンテナは不要になります。

### 追加のECHONET Liteプロパティを取得

`config/settings.yml`:
```yaml
acquisition:
  properties:
    - D3
    - D7
    - E1
    - E7
    - E0
    - E3
    - E8  # 定時積算電力量計測値（例）
```

## 依存関係の更新

```bash
# UV経由で依存関係を更新
uv pip install --upgrade pyserial pyyaml influxdb-client python-dotenv

# pyproject.tomlを更新後、Dockerイメージを再ビルド
docker compose build --no-cache
```

## 参考リンク

- [keilog GitHub](https://github.com/kjmat/keilog)
- [UV - Fast Python package installer](https://github.com/astral-sh/uv)
- [RL7023 Stick-D/IPS 製品情報](https://www.rohm.co.jp/products/wireless-communication/specified-low-power-radio-modules/bp35a1-product)
- [InfluxDB v2 Documentation](https://docs.influxdata.com/influxdb/v2/)
- [Telegraf Documentation](https://docs.influxdata.com/telegraf/latest/)

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。

## 注意事項

- Bルート認証情報は厳重に管理してください
- `.env`ファイルはGitにコミットしないでください（`.gitignore`に含まれています）
- スマートメーターへの過度なアクセスは避けてください（推奨: 30秒以上の間隔）
- keilogはGitサブモジュールとして管理されているため、クローン時に`--recursive`オプションを忘れずに
