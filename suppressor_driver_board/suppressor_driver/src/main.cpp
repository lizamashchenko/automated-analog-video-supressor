#include <Arduino.h>

const uint8_t FIRST_PIN = 2;   // D2 to D9
const uint8_t NUM_CHANNELS = 8;

// Protocol: each received byte is a bitmask of channel states.
// Bit 0 -> channel 1, bit 7 -> channel 8. 1 = on, 0 = off.

void setup() {
  Serial.begin(9600);
  for (uint8_t i = 0; i < NUM_CHANNELS; i++) {
    pinMode(FIRST_PIN + i, OUTPUT);
    digitalWrite(FIRST_PIN + i, LOW);
  }
}

void loop() {
  if (Serial.available()) {
    uint8_t mask = Serial.read();
    for (uint8_t i = 0; i < NUM_CHANNELS; i++) {
      digitalWrite(FIRST_PIN + i, (mask >> i) & 0x01 ? HIGH : LOW);
    }
  }
}
