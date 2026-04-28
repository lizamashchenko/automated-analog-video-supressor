#include <Arduino.h>
#include <SoftwareSerial.h>

const uint8_t SW_RX = 3;  // not used
const uint8_t SW_TX = 2;

SoftwareSerial linkSerial(SW_RX, SW_TX);  // RX, TX

void setup() {
  Serial.begin(9600);
  linkSerial.begin(9600);
}

void loop() {
  if (Serial.available()) {
    uint8_t ch = Serial.read();
    linkSerial.write(ch);
  }
}