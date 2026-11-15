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


class Sound:
    def __init__(self, cfg):
        self.cfg = cfg

    def ensure(self):
        try:
            os.makedirs(SOUND_DIR, exist_ok=True)
            send = os.path.join(SOUND_DIR, "send.wav")
            done = os.path.join(SOUND_DIR, "done.wav")
            if not os.path.exists(send):
                self._tone(send, [880], 0.045)
            if not os.path.exists(done):
                self._tone(done, [660, 990], 0.055)
        except Exception as exc:  # noqa: BLE001
            log.warning("生成声效失败：%s", exc)

    def play(self, name):
        if not getattr(self.cfg, "sound_effects", True):
            return
        path = os.path.join(SOUND_DIR, name + ".wav")
        if not os.path.exists(path):
            return
        for player in ("/usr/bin/pw-play", "/usr/bin/paplay"):
            if os.path.exists(player):
                threading.Thread(
                    target=lambda p=player, f=path: system.run([p, f], timeout=3),
                    daemon=True).start()
                return

    @staticmethod
    def _tone(path, freqs, dur, vol=0.10):
        rate = 44100
        data = []
        for f in freqs:
            n = int(rate * dur)
            for i in range(n):
                env = min(1.0, i / (rate * 0.008), (n - i) / (rate * 0.03))
                data.append(int(32767 * vol * env *
                                math.sin(2 * math.pi * f * i / rate)))
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"".join(
                struct.pack("<h", max(-32767, min(32767, v))) for v in data))
