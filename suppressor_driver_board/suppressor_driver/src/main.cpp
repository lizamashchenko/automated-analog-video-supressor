#include <Arduino.h>
#include <SoftwareSerial.h>

const uint8_t SW_RX = 10;
const uint8_t SW_TX = 11;  // not used

const uint8_t FIRST_PIN = 2;
const uint8_t NUM_CHANNELS  = 8;

SoftwareSerial linkSerial(SW_RX, SW_TX);

void setup() {
  Serial.begin(9600);
  Serial.println("Serial up");
  for (uint8_t i = 0; i < NUM_CHANNELS; i++) {
    pinMode(FIRST_PIN + i, OUTPUT);
    digitalWrite(FIRST_PIN + i, LOW);
  }

  linkSerial.begin(9600);

  delay(500);
  while (linkSerial.available()) linkSerial.read();
  Serial.println("Link serial setup done");
}

void loop() {
  if (linkSerial.available()) {
    uint8_t mask = linkSerial.read();

    for (uint8_t i = 0; i < NUM_CHANNELS; i++) {
      digitalWrite(FIRST_PIN + i, (mask >> i) & 0x01 ? HIGH : LOW);
      Serial.print("Activating a jammer at: "); Serial.println(i);
    }
  }
}

