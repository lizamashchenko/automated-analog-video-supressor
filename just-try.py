import SoapySDR
from SoapySDR import *
import numpy as np
import time

sdr = SoapySDR.Device(dict(driver="hackrf"))
sdr.setSampleRate(SOAPY_SDR_RX, 0, 20e6)
sdr.setGain(SOAPY_SDR_RX, 0, 8)

stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(stream)

buff = np.empty(131072, np.complex64)

print("Sweeping 4.9–5.1 GHz (drone ON)")

for f in range(2400, 2500, 2):
    sdr.setFrequency(SOAPY_SDR_RX, 0, f * 1e6)
    time.sleep(0.03)
    sr = sdr.readStream(stream, [buff], len(buff))
    if sr.ret > 0:
        samples = buff[:sr.ret] - np.mean(buff[:sr.ret])
        p = 10*np.log10(np.mean(np.abs(samples)**2) + 1e-12)
        print(f"{f} MHz : {p:.1f} dB")
