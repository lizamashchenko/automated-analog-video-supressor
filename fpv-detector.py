import SoapySDR
from SoapySDR import *
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, lfilter


# -------------------
# SDR Setup
# -------------------
sdr = SoapySDR.Device(dict(driver="hackrf"))
sdr.setSampleRate(SOAPY_SDR_RX, 0, 5e6)
sdr.setFrequency(SOAPY_SDR_RX, 0, 5800e6)
sdr.setGainMode(SOAPY_SDR_RX, 0, False)

sdr.setGain(SOAPY_SDR_RX, 0, "AMP", 1)
sdr.setGain(SOAPY_SDR_RX, 0, "LNA", 40)
sdr.setGain(SOAPY_SDR_RX, 0, "VGA", 40)


stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(stream)

N = 500000

buff = np.empty(N, np.complex64)

sr = sdr.readStream(stream, [buff], N)
samples = buff[:sr.ret]

samples = buff[:sr.ret]

spec = np.abs(np.fft.fftshift(np.fft.fft(samples)))
freqs = np.fft.fftshift(np.fft.fftfreq(len(spec), 1/5e6))

# plt.plot(freqs/1e6, 20*np.log10(spec+1e-9))
# plt.title("RF Spectrum Around Center")
# plt.xlabel("MHz Offset")
# plt.ylabel("dB")
# plt.grid()
# plt.show()


# -------------------
# FM Demod
# -------------------
# FM discriminator
phase = np.angle(samples[1:] * np.conj(samples[:-1]))

# Remove DC
phase -= np.mean(phase)

# Lowpass filter (video under ~3 MHz)
b, a = butter(5, 2e6/(5e6/2))

video = lfilter(b, a, phase)

# Window
video *= np.hanning(len(video))

# FFT
# spec = np.abs(np.fft.fft(video))
# freqs = np.fft.fftfreq(len(spec), 1/5e6)


# plt.plot(freqs[:len(freqs)//2], spec[:len(spec)//2])
# plt.xlim(0, 50000)
# plt.xlabel("Hz")
# plt.ylabel("Magnitude")
# plt.title("Demodulated Video Spectrum")
# plt.grid()
# plt.show()


# Autocorrelation
corr = np.correlate(video, video, mode='full')
corr = corr[len(corr)//2:]

# Convert lag to time
fs = 5e6
lags = np.arange(len(corr)) / fs

# Plot first 2 ms
plt.plot(lags*1e3, corr)
plt.xlim(0, 2)
plt.xlabel("Lag (ms)")
plt.ylabel("Correlation")
plt.title("Video Autocorrelation")
plt.grid()
plt.show()

