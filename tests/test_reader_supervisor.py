"""reader スレッドが死んだら作り直すこと（実機もブリッジも要らない）。

  uv run --with pytest --with pyserial pytest tests/

ここが壊れると、TCP 切断や USB 抜けのあと**プロセスは生きたままデータだけが
永久に止まる**（keilog の BrouteReader.run() には例外の受け止めが無い）。
"""
import logging
import os
import queue
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from smartmeter_logger import SmartMeterLogger  # noqa: E402


class FakeDev:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeReader:
    """BrouteReader の代わり。alive を自分で切り替えられる。"""

    def __init__(self, alive=True):
        self._alive = alive
        self.stopped = False
        self.wisundev = FakeDev()

    def is_alive(self):
        return self._alive

    def stop(self):
        self.stopped = True
        self._alive = False


def _logger(reader=None, init_ok=True):
    """設定ファイルを読まずに監視部分だけ組み立てる。"""
    lg = object.__new__(SmartMeterLogger)
    lg.logger = logging.getLogger('test')
    lg.data_queue = queue.Queue(50)
    lg.reader = reader
    lg.reader_restarts = 0
    lg._reader_retry_delay = 1.0
    lg._reader_retry_at = 0.0
    lg._reader_started_at = 0.0
    lg.init_calls = 0

    def fake_init():
        lg.init_calls += 1
        if init_ok:
            lg.reader = FakeReader(alive=True)
        return init_ok

    lg._init_broute_reader = fake_init
    return lg


def test_alive_reader_is_left_alone():
    lg = _logger(FakeReader(alive=True))
    lg._supervise_reader()
    assert lg.init_calls == 0
    assert lg.reader_restarts == 0


def test_dead_reader_is_recreated_and_queue_is_drained():
    dead = FakeReader(alive=False)
    lg = _logger(dead)
    lg.data_queue.put(['BR', 'E7', 123, 'OK'])   # 切断前の古い値
    lg.data_queue.put(['BR', 'E7', 456, 'OK'])

    lg._supervise_reader()

    assert lg.init_calls == 1
    assert lg.reader_restarts == 1
    assert dead.stopped is True            # 古いスレッドを確実に止めた
    assert dead.wisundev.closed is True    # 古いソケットを閉じた
    assert lg.data_queue.empty()           # 古い値を新 reader に混ぜない
    assert lg.reader.is_alive()


def test_failed_recreation_backs_off():
    lg = _logger(FakeReader(alive=False), init_ok=False)

    lg._supervise_reader()
    assert lg.init_calls == 1
    assert lg._reader_retry_delay == 2.0     # 1 → 2 秒
    assert lg._reader_retry_at > time.monotonic()

    # 期限前は再試行しない（毎周ループから呼ばれても連打しない）
    lg._supervise_reader()
    assert lg.init_calls == 1

    # 期限が来たら再試行する
    lg._reader_retry_at = 0.0
    lg._supervise_reader()
    assert lg.init_calls == 2
    assert lg._reader_retry_delay == 4.0


def test_reader_that_dies_right_after_start_is_also_backed_off():
    """**実機で踏んだ穴**: start() は成功するのに直後にスレッドが死ぬ。

    接続先が落ちていると serial_for_url が open() の中で例外を投げ、
    再生成は「成功」したのに reader はすぐ死ぬ。成功だけを見て
    バックオフを戻すと毎秒作り直して回り続ける。
    """
    lg = _logger(FakeReader(alive=False), init_ok=True)

    # 1 回目: 作り直し、2 秒後まで次を試さない
    lg._supervise_reader()
    assert lg.init_calls == 1
    assert lg._reader_retry_delay == 2.0

    # 作った reader が即死する
    lg.reader._alive = False
    lg._supervise_reader()
    assert lg.init_calls == 1, "期限前なのに作り直している"

    lg._reader_retry_at = 0.0
    lg._supervise_reader()
    assert lg.init_calls == 2
    assert lg._reader_retry_delay == 4.0


def test_backoff_resets_only_after_reader_is_stable():
    lg = _logger(FakeReader(alive=True))
    lg._reader_retry_delay = 32.0

    # 作った直後は生きているが、まだ安定とはみなさない
    lg._reader_started_at = time.monotonic()
    lg._supervise_reader()
    assert lg._reader_retry_delay == 32.0

    # READER_STABLE_SEC 以上生きていたら戻す
    lg._reader_started_at = time.monotonic() - SmartMeterLogger.READER_STABLE_SEC - 1
    lg._supervise_reader()
    assert lg._reader_retry_delay == 1.0
