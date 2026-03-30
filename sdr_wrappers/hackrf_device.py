import SoapySDR
from SoapySDR import *


class HackRFDevice:
    def __init__(self, sample_rate, lna_gain=32, vga_gain=32):
        self.sample_rate = sample_rate
        self.lna_gain = lna_gain
        self.vga_gain = vga_gain

        print("[INFO] Opening HackRF...")
        self.sdr = SoapySDR.Device(dict(driver="hackrf"))

        self._setup_device()
        self._setup_stream()

    def _setup_device(self):
        self.sdr.setSampleRate(SOAPY_SDR_RX, 0, self.sample_rate)

        self.sdr.setGain(SOAPY_SDR_RX, 0, False)
        self.sdr.setGain(SOAPY_SDR_RX, 0, "LNA", self.lna_gain)
        self.sdr.setGain(SOAPY_SDR_RX, 0, "VGA", self.vga_gain)

    def _setup_stream(self):
        self.rx_stream = self.sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
        self.sdr.activateStream(self.rx_stream)

    def tune(self, freq):
        self.sdr.setFrequency(SOAPY_SDR_RX, 0, freq)

    def read(self, buffer):
        sr = self.sdr.readStream(self.rx_stream, [buffer], len(buffer))
        return sr

    def close(self):
        self.sdr.deactivateStream(self.rx_stream)
        self.sdr.closeStream(self.rx_stream)