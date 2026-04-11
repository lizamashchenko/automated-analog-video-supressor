import SoapySDR
from SoapySDR import *
import numpy as np

CENTER_FREQ = 5840e6
SAMPLE_RATE = 20e6
GAIN = 35

DECIMATION = 10
FS_DECIM = SAMPLE_RATE / DECIMATION

FFT_SIZE = 4096
LINE_FREQ = 15625
THRESHOLD = 0.1

sdr = SoapySDR.Device(dict(driver="hackrf"))
sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)
sdr.setFrequency(SOAPY_SDR_RX, 0, CENTER_FREQ)
sdr.setGain(SOAPY_SDR_RX, 0, False)
sdr.setGain(SOAPY_SDR_RX, 0, "LNA", 32)
sdr.setGain(SOAPY_SDR_RX, 0, "VGA", 32)

rxStream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(rxStream)

buff = np.empty(262144, np.complex64)

print("Starting AUTOCORRELATION detection...")

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
    corr = np.correlate(x, x, mode='full')
    corr = corr[len(corr)//2:]

    corr /= np.max(corr) + 1e-6

    target_lag = int(FS_DECIM / LINE_FREQ)
    tol = int(0.1 * target_lag)
    if target_lag + tol >= len(corr):
        continue

    region = corr[target_lag - tol : target_lag + tol]
    peak = np.max(region)

    print(f"Autocorr peak: {peak:.3f}")

    if peak > THRESHOLD:
        print(">>> ANALOG VIDEO DETECTED (TIME DOMAIN) <<<")