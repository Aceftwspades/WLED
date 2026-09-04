"""
Live system audio, via WASAPI loopback.

This is the reason the simulator moved off the browser. A page can only reach
the speakers through getDisplayMedia - a screen-share picker, a permission
prompt, a checkbox the user has to find, and no guarantee about buffer size or
latency. WASAPI loopback is the supported Windows path for "capture what is
being played": no prompt, no picker, and the actual sample stream.

It opens the DEFAULT OUTPUT device's loopback endpoint, so whatever you are
listening to is what the cube sees. Audio is turned into sixteen band levels and
discarded; nothing is written to disk or sent anywhere.

Presents the same push(engine) call as synth.Synth, so the two are
interchangeable everywhere.
"""
import numpy as np

try:
    import pyaudiowpatch as pyaudio
except ImportError:                                    # pragma: no cover
    pyaudio = None


class LiveAudio:
    # Sixteen log-spaced bands, 50 Hz to 10 kHz. This APPROXIMATES the shape of
    # WLED's own sixteen bands rather than reproducing their exact edges - close
    # enough to judge an effect by, and not claimed to be more.
    LO, HI, BANDS = 50.0, 10000.0, 16

    # 2048 samples at 48 kHz is 23 Hz per bin and 43 ms of latency. 1024 halves
    # the latency and costs twice the bin width, which at the bottom of the
    # range is the difference between the lowest bands resolving and collapsing
    # onto each other - the bass bands are the ones driving beat detection, so
    # resolution wins.
    def __init__(self, gain=3.0, chunk=2048):
        if pyaudio is None:
            raise RuntimeError("pyaudiowpatch is not installed:  pip install pyaudiowpatch")
        self.gain = gain
        self.chunk = chunk
        self.p = pyaudio.PyAudio()
        dev = self._loopback_device()
        self.rate = int(dev["defaultSampleRate"])
        self.channels = int(dev["maxInputChannels"])
        self.name = dev["name"]
        self._buf = np.zeros(chunk, np.float32)
        self._win = np.hanning(chunk).astype(np.float32)
        self._edges = self._band_edges()
        self._prev_low = 0.0
        self._floor = 0.0
        self._primed = False
        self._agc = 1.0
        self.level = 0.0
        self.stream = self.p.open(
            format=pyaudio.paFloat32, channels=self.channels, rate=self.rate,
            input=True, input_device_index=dev["index"],
            frames_per_buffer=chunk, stream_callback=self._cb)

    def _loopback_device(self):
        """The loopback endpoint that belongs to the current default output."""
        api = self.p.get_host_api_info_by_type(pyaudio.paWASAPI)
        out = self.p.get_device_info_by_index(api["defaultOutputDevice"])
        if out.get("isLoopbackDevice"):
            return out
        for lb in self.p.get_loopback_device_info_generator():
            if out["name"] in lb["name"]:
                return lb
        raise RuntimeError(
            f"no loopback endpoint for default output {out['name']!r}. "
            "Windows exposes one per output device; if this persists, check that "
            "the device is not exclusive-mode locked by another application.")

    def _band_edges(self):
        """Log-spaced, and forced strictly increasing.

        A log spacing packs the low bands close together, and down there the
        bins are wider than the bands are: at 48 kHz with a 1024 chunk the first
        two edges both landed on bin 1, so bands 0 and 1 read identical values
        and the bottom of the spectrum was a duplicate rather than a reading.
        Nudging each edge past the last costs a little accuracy in band centres
        and buys every band its own data.
        """
        n = self.chunk // 2 + 1
        e, prev = [], -1
        for i in range(self.BANDS + 1):
            f = self.LO * (self.HI / self.LO) ** (i / self.BANDS)
            b = int(round(f / (self.rate / 2.0) * n))
            b = max(b, prev + 1)
            e.append(min(n - 1, b))
            prev = e[-1]
        return e

    def _cb(self, data, frames, time_info, status):
        a = np.frombuffer(data, np.float32)
        if self.channels > 1:
            a = a.reshape(-1, self.channels).mean(axis=1)     # downmix
        if a.size >= self.chunk:
            self._buf = a[-self.chunk:].copy()
        return (None, pyaudio.paContinue)

    def push(self, eng):
        """Fill the engine's FFT bins from the most recent audio, and detect onsets."""
        spec = np.abs(np.fft.rfft(self._buf * self._win))
        raw = np.empty(self.BANDS, np.float32)
        for i in range(self.BANDS):
            a, b = self._edges[i], max(self._edges[i] + 1, self._edges[i + 1])
            raw[i] = spec[a:b].mean()

        # Automatic gain, because a fixed multiplier cannot serve real music.
        #
        # This was a flat x40, and at that ordinary programme material clipped
        # 18% of all band samples flat against 255. A clipped band is a
        # CONSTANT, so anything watching for onsets sees nothing at all in
        # exactly the bands carrying the music. Dropping it to x10 fixed the
        # passage it was measured on and then clipped 16% on the next one, four
        # minutes later - the dynamic range between a quiet verse and a chorus
        # is far wider than any one number can straddle.
        #
        # So: track the loudest band with a fast attack and a slow release, and
        # normalise against it. The loudest band lands near 200, leaving real
        # headroom for a transient, and quiet passages come up instead of
        # disappearing. gain stays as a trim on top.
        peak = float(raw.max())
        if peak > self._agc:
            self._agc = peak                                  # instant attack
        else:
            self._agc += (peak - self._agc) * 0.010           # ~2 s release
        ref = max(self._agc, 0.35)                            # floor: silence stays silent
        scaled = np.clip(raw * (200.0 / ref) * self.gain, 0.0, 255.0)

        arr = eng.fft
        for i in range(self.BANDS):
            arr[i] = int(scaled[i])
        self.level = float(scaled.mean())

        # Onset by spectral flux on the low bands - the transient shape
        # fx_lowBeat is looking for. The floor attacks fast and decays slowly,
        # so sustained bass stops triggering while a kick over it still does.
        low = (int(arr[0]) + int(arr[1]) + int(arr[2])) / 3.0
        if not self._primed:                    # nothing to difference against yet
            self._primed = True
            self._prev_low = low
            eng.audio(min(255.0, self.level * 1.6), 0)
            return 0
        flux = max(0.0, low - self._prev_low)
        self._prev_low = low
        self._floor = max(flux, self._floor * 0.92)
        hit = 1 if (flux > 8 and flux >= self._floor * 0.85 and low > 40) else 0
        eng.audio(min(255.0, self.level * 1.6), hit)
        return hit

    def close(self):
        try:
            self.stream.stop_stream(); self.stream.close()
        finally:
            self.p.terminate()
