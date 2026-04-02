import SoapySDR
from SoapySDR import *
import numpy as np
import time
import os
from datetime import datetime

MIN_FREQ = 1000e6
MAX_FREQ = 6000e6

SAMPLE_RATE = 20e6
STEP = 18e6

WIDE_SAMPLING_NUM = 10
BUFFER_SIZE = 262144

SETTLE_TIME = 0.01
FLUSH_BUFFERS = 3

BASE_DIR = "/home/liza/UCU/diploma/dataset/iq_recordings"

timestamp_run = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = os.path.join(BASE_DIR, f"sweep_{timestamp_run}")
os.makedirs(OUTPUT_DIR, exist_ok=True)

IQ_FILE = os.path.join(OUTPUT_DIR, "iq.bin")
META_FILE = os.path.join(OUTPUT_DIR, "metadata.csv")

sdr = SoapySDR.Device(dict(driver="hackrf"))

sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)
sdr.setGain(SOAPY_SDR_RX, 0, "LNA", 32)
sdr.setGain(SOAPY_SDR_RX, 0, "VGA", 32)

rx_stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(rx_stream)

buff = np.empty(BUFFER_SIZE, np.complex64)

meta_f = open(META_FILE, "w")
meta_f.write("timestamp,center_freq,offset_bytes,num_samples\n")

iq_f = open(IQ_FILE, "ab")  # append binary

byte_offset = 0

current_freq = MIN_FREQ

while current_freq < MAX_FREQ:
    print(f"\n[SCAN] {current_freq/1e6:.1f} MHz")

    sdr.setFrequency(SOAPY_SDR_RX, 0, current_freq)
    time.sleep(SETTLE_TIME)

    for _ in range(FLUSH_BUFFERS):
        sdr.readStream(rx_stream, [buff], len(buff))

    for i in range(WIDE_SAMPLING_NUM):
        sr = sdr.readStream(rx_stream, [buff], len(buff))

        if sr.ret <= 0:
            print(f"Bad read: ret {sr.ret}")
            continue

        samples = buff.copy()

        samples.tofile(iq_f)

        num_samples = len(samples)

        timestamp = datetime.utcnow().isoformat()
        meta_f.write(f"{timestamp},{current_freq},{byte_offset},{num_samples}\n")

        byte_offset += num_samples * 8

        print(f"Saved chunk @ {current_freq/1e6:.1f} MHz (offset {byte_offset})")

    current_freq += STEP

iq_f.close()
meta_f.close()

sdr.deactivateStream(rx_stream)
sdr.closeStream(rx_stream)

print("\nRecording complete")