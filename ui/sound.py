"""面板提示音：启动时生成两个很短的 wav，播放交给系统播放器。"""

from __future__ import annotations

import logging
import math
import os
import struct
import threading
import wave

from core import system

log = logging.getLogger(__name__)

SOUND_DIR = "/tmp/archlot-sounds"

# PipeWire 的 sink 会空闲挂起，恢复时的前几十毫秒可能被吞掉。
# 所以每段声音前面留一小段静音，并把音效做得比原来长一些。
_LEAD = 0.09
_MIN_DURATION = 0.12


class Sound:
    def __init__(self, cfg):
        self.cfg = cfg

    def ensure(self):
        try:
            os.makedirs(SOUND_DIR, exist_ok=True)
            send = os.path.join(SOUND_DIR, "send.wav")
            done = os.path.join(SOUND_DIR, "done.wav")
            if not self._usable(send):
                self._tone(send, [880], 0.14)
            if not self._usable(done):
                self._tone(done, [660, 990], 0.11)
        except Exception as exc:  # noqa: BLE001
            log.warning("生成声效失败：%s", exc)

    def play(self, name):
        if not getattr(self.cfg, "sound_effects", True):
            return
        path = os.path.join(SOUND_DIR, name + ".wav")
        if not os.path.exists(path):
            # /tmp 可能被清理；临场补一遍，避免静默失效。
            self.ensure()
            if not os.path.exists(path):
                return
        for player in ("/usr/bin/pw-play", "/usr/bin/paplay"):
            if os.path.exists(player):
                threading.Thread(
                    target=self._play_file, args=(player, path),
                    daemon=True).start()
                return

    @staticmethod
    def _play_file(player, path):
        rc, _, err = system.run([player, path], timeout=3)
        if rc != 0:
            log.warning("播放声效失败（%s, rc=%s）：%s",
                        os.path.basename(player), rc, (err or "").strip()[:200])

    @staticmethod
    def _usable(path):
        """旧版本生成的是 45ms 的短音，重写成长一点的版本。"""
        try:
            with wave.open(path, "rb") as w:
                return w.getnframes() / float(w.getframerate()) >= _MIN_DURATION
        except (OSError, EOFError, wave.Error):
            return False

    @staticmethod
    def _tone(path, freqs, dur, vol=0.16, rate=44100):
        data = [0] * int(rate * _LEAD)
        for f in freqs:
            n = int(rate * dur)
            for i in range(n):
                env = min(1.0, i / (rate * 0.010), (n - i) / (rate * 0.035))
                data.append(int(32767 * vol * env *
                                math.sin(2 * math.pi * f * i / rate)))
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"".join(
                struct.pack("<h", max(-32767, min(32767, v))) for v in data))
