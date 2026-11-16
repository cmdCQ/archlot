"""面板提示音：启动时生成两个很短的 wav，播放交给系统播放器。

音色刻意做得低、软：低频正弦 + 少量二次谐波，慢起音、指数衰减，
避免高频纯音的“叮”声刺耳。版本号变了会自动重新生成。
"""

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
_GAP = 0.018
_MIN_DURATION = 0.12
_TONE_VERSION = 3


class Sound:
    def __init__(self, cfg):
        self.cfg = cfg

    @staticmethod
    def _path(name):
        return os.path.join(SOUND_DIR, f"{name}-v{_TONE_VERSION}.wav")

    def ensure(self):
        try:
            os.makedirs(SOUND_DIR, exist_ok=True)
            send = self._path("send")
            done = self._path("done")
            if not self._usable(send):
                self._tone(send, [523.25], 0.16, vol=0.12)
            if not self._usable(done):
                self._tone(done, [440.0, 659.25], 0.15, vol=0.12)
        except Exception as exc:  # noqa: BLE001
            log.warning("生成声效失败：%s", exc)

    def play(self, name):
        if not getattr(self.cfg, "sound_effects", True):
            return
        path = self._path(name)
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
        """旧版本生成的是高频短音，重写成长一点的柔和版本。"""
        try:
            with wave.open(path, "rb") as w:
                return w.getnframes() / float(w.getframerate()) >= _MIN_DURATION
        except (OSError, EOFError, wave.Error):
            return False

    @staticmethod
    def _tone(path, freqs, dur, vol=0.12, rate=44100):
        data = [0] * int(rate * _LEAD)
        for idx, f in enumerate(freqs):
            if idx:
                data.extend([0] * int(rate * _GAP))
            n = int(rate * dur)
            for i in range(n):
                t = i / rate
                attack = min(1.0, i / (rate * 0.018))
                release = min(1.0, (n - i) / (rate * 0.045))
                decay = math.exp(-t / (dur * 0.75))
                # 基频 + 一点点二次谐波：比纯正弦更有“木头/铃”的暖度，
                # 又不会像高频纯音那样扎耳朵。
                body = (math.sin(2 * math.pi * f * t)
                        + 0.16 * math.sin(4 * math.pi * f * t)
                        * math.exp(-t / (dur * 0.35)))
                data.append(int(32767 * vol * attack * release * decay * body))
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"".join(
                struct.pack("<h", max(-32767, min(32767, v))) for v in data))
