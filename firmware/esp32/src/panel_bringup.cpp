#include <Arduino.h>
#include <cstring>
#include <TFT_eSPI.h>
#include "boards/seeed_xiao_s3_wio_epaper.h"

// Manufacturer Setup502: SKU104990861, UC8179, 800x480 monochrome.
// This intentionally uses Seeed_GFX's HSPI setup, not ReferenceSpi.
// No radio driver/tasks may run in this isolated panel test.
static_assert(TFT_WIDTH == 800 && TFT_HEIGHT == 480, "Wrong panel geometry");
static_assert(TFT_CS == otd::reference_board::epaper_cs, "Wrong carrier CS");
static_assert(TFT_BUSY == otd::reference_board::epaper_busy, "Wrong carrier BUSY");
static_assert(TFT_RST == otd::reference_board::epaper_rst, "Wrong carrier RESET");
static_assert(TFT_DC == otd::reference_board::epaper_dc, "Wrong carrier DC");
static_assert(TFT_SCLK == otd::reference_board::spi_sck &&
              TFT_MOSI == otd::reference_board::spi_mosi, "Wrong SPI wiring");

bool attempted = false;
char command[8] = {};
size_t used = 0;
bool overflow = false;

void renderTest() {
  if (attempted) {
    Serial.println("Test already attempted. Reset the board to run again.");
    return;
  }
  attempted = true;
  static EPaper display;
  if (!display.getPointer()) {
    Serial.println("Framebuffer allocation failed; panel left untouched.");
    return;
  }
  Serial.println("Starting one full refresh. Inspect serial output for driver timeouts.");
  display.begin();
  display.fillScreen(TFT_WHITE);
  display.drawRect(0, 0, 800, 480, TFT_BLACK);
  display.fillRect(12, 12, 24, 24, TFT_BLACK);
  display.drawRect(764, 12, 24, 24, TFT_BLACK);
  display.setTextColor(TFT_BLACK, TFT_WHITE);
  display.setTextSize(2);
  display.drawString("TOP LEFT", 46, 16);
  display.drawString("TOP RIGHT", 630, 48);
  display.setTextSize(4);
  display.drawString("Open Transit Display", 40, 110);
  display.setTextSize(2);
  display.drawString("PANEL TEST ONLY", 40, 180);
  display.drawString("Seeed 104990861 / UC8179 / 800 x 480", 40, 220);
  display.drawString("XIAO ESP32-S3 + ePaper Driver Board v2", 40, 260);
  display.drawString("Radio inactive - no live transit data", 40, 300);
  for (int i = 0; i < 16; ++i) {
    if ((i & 1) == 0) display.fillRect(40 + i * 40, 350, 40, 40, TFT_BLACK);
  }
  display.drawString("BOTTOM LEFT", 12, 438);
  display.drawString("BOTTOM RIGHT", 640, 438);
  display.update(); // manufacturer's full update returns panel to sleep
  Serial.println("Refresh sequence returned. Check orientation, border and black/white bars visually.");
  Serial.println("No automatic repeats. Radio, Wi-Fi and incoming notices remain inactive.");
}

void setup() {
  digitalWrite(otd::reference_board::radio_cs, HIGH);
  pinMode(otd::reference_board::radio_cs, OUTPUT);
  digitalWrite(otd::reference_board::epaper_cs, HIGH);
  pinMode(otd::reference_board::epaper_cs, OUTPUT);
  Serial.begin(115200);
  const uint32_t start = millis();
  while (!Serial && millis() - start < 3000) delay(10);
  Serial.println("Seeed 104990861 panel test. Send TEST followed by newline to draw once.");
}

void loop() {
  while (Serial.available()) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\r') continue;
    if (c == '\n') {
      command[used] = '\0';
      if (!overflow && std::strcmp(command, "TEST") == 0) renderTest();
      else Serial.println("Send TEST followed by newline.");
      used = 0;
      overflow = false;
    } else if (used < sizeof(command) - 1) command[used++] = c;
    else overflow = true;
  }
  delay(10);
}
