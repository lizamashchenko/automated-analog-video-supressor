import SoapySDR
from SoapySDR import *
import numpy as np

CENTER_FREQ = 5840e6
SAMPLE_RATE = 10e6
GAIN = 35

DECIMATION = 10
FS_DECIM = SAMPLE_RATE / DECIMATION

FFT_SIZE = 8192
LINE_FREQ = 15625
THRESHOLD = 2

sdr = SoapySDR.Device(dict(driver="hackrf"))
sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)
sdr.setFrequency(SOAPY_SDR_RX, 0, CENTER_FREQ)
sdr.setGain(SOAPY_SDR_RX, 0, False)
sdr.setGain(SOAPY_SDR_RX, 0, "LNA", 32)
sdr.setGain(SOAPY_SDR_RX, 0, "VGA", 32)

rxStream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(rxStream)

buff = np.empty(262144, np.complex64)

print("Starting cyclostationary detection...")

while True:
    sr = sdr.readStream(rxStream, [buff], len(buff))
    if sr.ret <= 0:
        continue

    iq = buff[:sr.ret]
    iq = iq[::DECIMATION]

    inst_freq = np.angle(iq[1:] * np.conj(iq[:-1]))
    inst_freq -= np.mean(inst_freq)

    if len(inst_freq) < FFT_SIZE:
        continue

    x = inst_freq[:FFT_SIZE]
    x *= np.hanning(FFT_SIZE)

    S = np.fft.fft(x)
    freqs = np.fft.fftfreq(FFT_SIZE, 1/FS_DECIM)
    S_mag = np.abs(S)

    idx = np.argmin(np.abs(freqs - LINE_FREQ))

    signal_power = S_mag[idx]
    noise_floor = np.mean(S_mag)

    ratio = signal_power / (noise_floor + 1e-6)

    print(f"Ratio: {ratio:.2f}")

    if ratio > THRESHOLD:
        print(">>> ANALOG VIDEO DETECTED <<<")
    