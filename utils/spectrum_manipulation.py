import numpy as np

FFT_SMOOTHING_FACTOR = 0.2
SAMPLE_RATE = 20e6  # Hz

# Build spectrum
def compute_power_spectrum(samples, state):
    window = np.hanning(len(samples))
    spectrum = np.fft.fftshift(np.fft.fft(samples * window))
    power = 20 * np.log10(np.abs(spectrum) + 1e-12)

    center = len(power) // 2
    power[center-5:center+5] = np.median(power)

    if state.avg_power is None:
        state.avg_power = power
    else:
        alpha = FFT_SMOOTHING_FACTOR
        state.avg_power = alpha * power + (1 - alpha) * state.avg_power

    return state.avg_power

def get_freq_key(freq):
    return int(freq / SAMPLE_RATE) 

