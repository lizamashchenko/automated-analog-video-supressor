import threading
import time

import serial

# a class representing a jammer
class Jammer:
    def __init__(self, port, baud, ranges, hold_seconds, logger=None, on_event=None):
        self.port         = port
        self.baud         = baud
        self.ranges       = [(int(lo), int(hi)) for lo, hi in ranges]
        self.hold_seconds = hold_seconds
        self.logger       = logger
        self.on_event     = on_event or (lambda t, d: None)

        self._lock     = threading.Lock()
        self._ser      = None
        self._active   = {}
        self._deadline = {}

    def open(self):
        self._ser = serial.Serial(self.port, self.baud, timeout=1)
        # Arduino Nano resets on serial open; wait for bootloader.
        time.sleep(2)
        self._send_state()

    def close(self):
        with self._lock:
            for timer in self._active.values():
                timer.cancel()
            self._active.clear()
            self._deadline.clear()
        if self._ser:
            try:
                self._ser.write(b"\x00")
                self._ser.flush()
            except Exception:
                pass
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def channel_for_freq(self, freq):
        for i, (lo, hi) in enumerate(self.ranges):
            if lo <= freq < hi:
                return i + 1
        return None

    def is_jammed(self, freq):
        ch = self.channel_for_freq(freq)
        if ch is None:
            return False
        with self._lock:
            return ch in self._deadline and self._deadline[ch] > time.monotonic()

    def jammed_overlap(self, lo, hi):
        with self._lock:
            now = time.monotonic()
            for ch, deadline in self._deadline.items():
                if deadline <= now:
                    continue
                jlo, jhi = self.ranges[ch - 1]
                if jlo < hi and jhi > lo:
                    return (jlo, jhi)
        return None

    def activate(self, freq):
        ch = self.channel_for_freq(freq)
        if ch is None:
            return None

        with self._lock:
            existing = self._active.pop(ch, None)
            if existing is not None:
                existing.cancel()

            self._deadline[ch] = time.monotonic() + self.hold_seconds
            timer = threading.Timer(self.hold_seconds, self._deactivate, args=(ch,))
            timer.daemon = True
            self._active[ch] = timer
            timer.start()

            self._send_state_locked()

        return ch

    def _deactivate(self, ch):
        with self._lock:
            self._active.pop(ch, None)
            self._deadline.pop(ch, None)
            self._send_state_locked()
        self.on_event("jammer_deactivated", {"channel": ch})

    def _send_state(self):
        with self._lock:
            self._send_state_locked()

    def _send_state_locked(self):
        if not self._ser:
            return
        mask = 0
        for ch in self._deadline:
            mask |= 1 << (ch - 1)
        try:
            self._ser.write(bytes([mask & 0xFF]))
            self._ser.flush()
        except Exception as e:
            self.on_event("error", {"error_type": "JAMMER_SEND", "message": str(e)})
