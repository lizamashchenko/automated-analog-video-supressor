import argparse
import SoapySDR
from SoapySDR import *
import numpy as np
import time
import os
from datetime import datetime
from config import load as load_config

cfg = load_config()

MIN_FREQ          = cfg["sdr"]["min_freq"]
MAX_FREQ          = cfg["sdr"]["max_freq"]
SAMPLE_RATE       = cfg["sdr"]["sample_rate"]
BUFFER_SIZE       = cfg["sdr"]["buffer_size"]
LNA_GAIN          = cfg["sdr"]["lna_gain"]
VGA_GAIN          = cfg["sdr"]["vga_gain"]
WIDE_SAMPLING_NUM = cfg["scan"]["wide_sampling_num"]

SETTLE_TIME   = 0.01
FLUSH_BUFFERS = 3

parser = argparse.ArgumentParser(description="Record a full-spectrum IQ sweep to disk")
parser.add_argument("--base-dir", metavar="DIR",
                    default="/home/liza/UCU/diploma/dataset/iq_recordings",
                    help="Directory where sweep folders are created")
args = parser.parse_args()

timestamp_run = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = os.path.join(args.base_dir, f"sweep_{timestamp_run}")
os.makedirs(OUTPUT_DIR, exist_ok = True)

IQ_FILE   = os.path.join(OUTPUT_DIR, "iq.bin")
META_FILE = os.path.join(OUTPUT_DIR, "metadata.csv")

sdr = SoapySDR.Device(dict(driver="hackrf"))
sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)
sdr.setGain(SOAPY_SDR_RX, 0, "LNA", LNA_GAIN)
sdr.setGain(SOAPY_SDR_RX, 0, "VGA", VGA_GAIN)

rx_stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(rx_stream)

buff = np.empty(BUFFER_SIZE, np.complex64)

meta_f = open(META_FILE, "w")
meta_f.write("timestamp,center_freq,offset_bytes,num_samples\n")

iq_f = open(IQ_FILE, "ab")

byte_offset = 0
current_freq = MIN_FREQ

while current_freq < MAX_FREQ:
    print(f"\n[SCAN] {current_freq/1e6:.1f} MHz")

    sdr.setFrequency(SOAPY_SDR_RX, 0, current_freq)
    time.sleep(SETTLE_TIME)

    for _ in range(FLUSH_BUFFERS):
        sdr.readStream(rx_stream, [buff], len(buff))

    for _ in range(WIDE_SAMPLING_NUM):
        sr = sdr.readStream(rx_stream, [buff], len(buff))

        if sr.ret <= 0:
            print(f"Bad read: ret {sr.ret}")
            continue

        samples = buff.copy()
        samples.tofile(iq_f)

        timestamp = datetime.utcnow().isoformat()
        meta_f.write(f"{timestamp},{current_freq},{byte_offset},{len(samples)}\n")

        byte_offset += len(samples) * 8
        print(f"Saved chunk @ {current_freq/1e6:.1f} MHz (offset {byte_offset})")

    current_freq += SAMPLE_RATE

iq_f.close()
meta_f.close()

sdr.deactivateStream(rx_stream)
sdr.closeStream(rx_stream)

print("\nRecording complete")
print(f"Output: {OUTPUT_DIR}")
