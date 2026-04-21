import argparse
import threading

from utils.config import load as load_config
from detector import Detector

# TODO
# no tagged freq, can read old samples
# test UI functionality
# tune params
# final clean up and README update
# add help function

parser = argparse.ArgumentParser(description="Full-spectrum FPV drone detector")
parser.add_argument("--classifier", choices=["harmonic", "cyclo", "autocorr"], help="Classifier to use (overrides config)")
parser.add_argument("--device", choices=["hackrf", "file"], help="Device type (overrides config)")
parser.add_argument("--file-path", metavar="PATH", help="IQ binary file path (required when --device=file)")
parser.add_argument("--metadata-path", metavar="PATH", help="Metadata CSV path (required when --device=file)")
parser.add_argument("--run-name", metavar="NAME", help="Name for this run's log folder (default: timestamp)")
parser.add_argument("--verbosity", type=int, choices=[0, 1, 2, 3, 4], metavar="0-4", help="Log detail level (overrides config)")
parser.add_argument("--min-freq", type=float, metavar="HZ", help="Start frequency in Hz (overrides config)")
parser.add_argument("--max-freq", type=float, metavar="HZ", help="End frequency in Hz (overrides config)")
parser.add_argument("--sweeps", type=int, default=0, metavar="N", help="Number of full sweeps to run, 0 = run forever (default: 0)")

args = parser.parse_args()
cfg = load_config()

if args.device:
    cfg["device"]["type"] = args.device
if args.file_path:
    cfg["device"]["file_path"] = args.file_path
if args.metadata_path:
    cfg["device"]["metadata_path"] = args.metadata_path
if args.classifier:
    cfg["detection"]["active_classifier"] = args.classifier
if args.verbosity:
    cfg["logging"]["verbosity"] = args.verbosity
if args.min_freq:
    cfg["sdr"]["min_freq"] = args.min_freq
if args.max_freq:
    cfg["sdr"]["max_freq"] = args.max_freq

cfg["sweeps"] = args.sweeps

_print_lock = threading.Lock()
_on_progress = False

def _clear_progress():
    global _on_progress
    if _on_progress:
        print(f"\r{' ' * 80}\r", end="", flush=True)
        _on_progress = False

def _print_event(event_type, data):
    global _on_progress

    with _print_lock:
        if event_type == "freq_update":
            _on_progress = True
            print(f"\r  scanning {data['freq'] / 1e6:.1f} MHz  "
                  f"[{'#' * int(data['progress'] * 30):<30}] "
                  f"{data['progress'] * 100:.0f}%",
                  end="", flush=True)
            return

        _clear_progress()

        if event_type == "status":
            print(f"[{data['state'].upper()}]" +
                  (f"  run: {data['run_name']}" if "run_name" in data else ""))
        elif event_type == "sweep_start":
            print(f"\n{'=' * 60}")
            print(f"Sweep {data['sweep_num'] + 1}  "
                  f"{data['min_freq'] / 1e6:.0f}–{data['max_freq'] / 1e6:.0f} MHz")
            print("=" * 60)
        elif event_type == "plateau_confirmed":
            print(f"  [PLATEAU] {data['freq'] / 1e6:.1f} MHz  "
                  f"bw={data['bandwidth']:.1f} MHz  hits={data['hits']}")
        elif event_type == "video_confirmed":
            print(f"  [CONFIRMED] {data['freq'] / 1e6:.1f} MHz  "
                  f"{data['classifier']}  score={data['score']:.2f}")
        elif event_type == "video_rejected":
            print(f"  [rejected]  {data['freq'] / 1e6:.1f} MHz  "
                  f"{data['classifier']}  score={data['score']:.2f}")
        elif event_type == "sweep_complete":
            print(f"\nSweep {data['sweep_num'] + 1} done  plateaus={data['plateaus']}")
            print("-" * 60)
        elif event_type == "error":
            freq = data.get("freq", "")
            print(f"  [ERROR] {data['error_type']}  {data['message']}"
                  + (f"  @ {freq/1e6:.1f} MHz" if freq else ""))


detector = Detector(cfg, on_event = _print_event)
detector.start(run_name = args.run_name)

try:
    detector.join()

except KeyboardInterrupt:
    print("\nStopping...")
    detector.stop()
