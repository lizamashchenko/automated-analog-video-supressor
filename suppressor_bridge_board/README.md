# Suppressor Bridge Board

Arduino Nano firmware that bridges the host PC's USB serial onto a wired link going out to the [suppressor driver board](../suppressor_driver_board/) at the antenna site. Every byte received from the PC is re-emitted on a software UART pin and travels down a twisted pair lifted from a piece of Ethernet cable.

This board sits on the **PC end** of the link.

## Role in the system

```
HackRF One ──► detector.py ──► utils/jammer.py ──USB serial──► bridge board ──twisted pair──► driver board ──► 8× jammer modules
```

The bridge is intentionally dumb: it has no protocol awareness, no buffering, no acknowledgement. It exists so the detector can stay at the operator workstation while the jammer modules are placed several metres away with only a thin signalling cable between them.

## Hardware

- **MCU board**: Arduino Nano (ATmega328P, 5 V, 16 MHz)
- **PC link**: hardware UART over USB, 9600 baud, 8N1 — appears as `/dev/ttyUSB*` on the host
- **Outgoing link**: software UART **TX on D2**, 9600 baud, 8N1
- **Cable**: one twisted pair from a length of Ethernet cable
  - one conductor of the pair carries the `D2` signal to the driver board's `D10`
  - the second conductor of the pair carries `GND`, tied together with the cable's foil/braid shield, common with the driver-board side
- **Power**: USB from the host PC

## Serial protocol

The bridge does not interpret the byte stream — see the [driver-board README](../suppressor_driver_board/README.md#serial-protocol) for the channel-bitmask encoding. From the PC's perspective the bridge looks like a plain `/dev/ttyUSB*` running at 9600 baud, 8N1.

## Build and flash

The firmware is a standard PlatformIO project under [`bridge_board/`](bridge_board/).

```bash
cd suppressor_bridge_board/bridge_board
pio run                # compile
pio run -t upload      # flash the connected Nano
pio device monitor     # serial monitor at 9600 baud
```

If `pio` is not installed: `pip install platformio`, or use the PlatformIO IDE extension in VS Code.

The target environment is defined in [`platformio.ini`](bridge_board/platformio.ini):

```ini
[env:nanoatmega328]
platform = atmelavr
board = nanoatmega328
framework = arduino
```

If your Nano uses the new bootloader, change `board = nanoatmega328new`.

## Power-up order

The bridge board **must be powered before** the detector opens its serial port — see the [project README](../README.md#power-up-order) for the full sequence and the required init delay.
