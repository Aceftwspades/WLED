"""
The synthetic audio generator, ported line for line from index.html.

This exists so native measurements can be held against the browser ones. If the
two front ends fed the effects different audio, every number either produced
would be incomparable and the parity check that lets us retire the browser build
would be meaningless.

Real audio lives in audio.py. This is the repeatable stand-in.
"""
import math


class Synth:
    def __init__(self, vol=90, bass=45, mid=50, treb=35, bpm=120, auto_beat=True):
        self.vol, self.bass, self.mid, self.treb = vol, bass, mid, treb
        self.bpm, self.auto_beat = bpm, auto_beat
        self.muted = False
        self.last_beat = -1e9
        self.kick_req = False

    def push(self, eng):
        """Fill the engine's FFT bins and volume for the current simulated time."""
        arr = eng.fft
        if self.muted:
            arr[:] = 0
            eng.audio(0.0, 0)
            return 0

        # Beat timing runs on the SIMULATED clock, so stepping frame by frame
        # cannot drift relative to the beat.
        period = 60000.0 / max(1, self.bpm)
        fire = self.kick_req
        if self.auto_beat and (eng.sim_ms - self.last_beat) >= period:
            fire = True
        if fire:
            self.last_beat = eng.sim_ms
            self.kick_req = False

        # A kick that decays over ~200 ms, so the low band genuinely rises above
        # its floor and falls back - a transient, not a louder held note. A
        # constant bass can never pass fx_lowBeat's rise test, because the floor
        # simply climbs to meet it.
        kick = max(0.0, 165.0 * (1.0 - (eng.sim_ms - self.last_beat) / 200.0))

        T = eng.sim_ms / 1000.0
        for i in range(16):
            if i < 3:
                base = self.bass
            elif i < 9:
                base = self.bass + (self.mid - self.bass) * ((i - 3) / 6.0)
            else:
                base = self.mid + (self.treb - self.mid) * ((i - 9) / 7.0)
            wob = 0.55 * base * (
                0.5 * math.sin(T * (0.7 + i * 0.13) + i * 1.7)
                + 0.3 * math.sin(T * (1.9 + i * 0.07) + i * 0.9)
                + 0.2 * math.sin(T * (3.3 - i * 0.05) + i * 2.6))
            v = base + wob + (kick if i < 3 else 0.0)
            arr[i] = int(max(0, min(255, int(v))))

        # peak is set for exactly the firing frame: leaving it high latches
        # prevPeak inside fx_lowBeat and suppresses every later beat.
        peak = 1 if fire else 0
        eng.audio(min(255.0, self.vol + kick * 0.4), peak)
        return peak
