#pragma once
#include <GxEPD2.h>
#include <gdey/GxEPD2_750_GDEY075T7.h>

class OTDDifferentialRefresh {
public:
  bool update(EPaper& sprite, SPIClass& spi, bool forceFull) {
    if (failed) return false;
    const auto* pixels = static_cast<const uint8_t*>(sprite.getPointer());
    if (!pixels) return false;
#ifdef EPD_HORIZONTAL_MIRROR
    for (int y = 0; y < 480; ++y) {
      for (int x = 0; x < 100; ++x) {
        uint8_t b = pixels[y * 100 + 99 - x];
        b = (b >> 4) | (b << 4);
        b = ((b & 0xcc) >> 2) | ((b & 0x33) << 2);
        current[y * 100 + x] = ((b & 0xaa) >> 1) | ((b & 0x55) << 1);
      }
    }
#else
    memcpy(current, pixels, sizeof current);
#endif
    const bool full = forceFull || !valid || partials >= 4;
    // The Wio can reset the controller during TX. Reinitialize with the
    // radio in standby and reload both planes from ESP32 memory every time.
    panel.selectSPI(spi, SPISettings(4000000, MSBFIRST, SPI_MODE0));
    panel.init(0, !valid, 10, false);
    panel.setBusyCallback(onBusy, this);
    panel.writeImageToPrevious(valid ? previous : current, 0, 0, 800, 480);
    panel.writeImage(current, 0, 0, 800, 480);
    sawBusy = false;
    const uint32_t start = millis();
    panel.refresh(!full);
    const uint32_t elapsed = millis() - start;
    const bool ok = sawBusy && digitalRead(4) == HIGH && elapsed < 10000;
    panel.powerOff();
    failed = !ok || digitalRead(4) != HIGH;
    if (failed) return false;
    valid = true;
    partials = full ? 0 : partials + 1;
    memcpy(previous, current, sizeof previous);
    Serial.printf("EPD %s driver=GxEPD2 drive_ms=%lu partials=%u\n",
                  full ? "FULL" : "DIFF", (unsigned long)elapsed, partials);
    return true;
  }

private:
  static void onBusy(const void* context) {
    static_cast<OTDDifferentialRefresh*>(const_cast<void*>(context))->sawBusy = true;
    delay(1);
  }
  GxEPD2_750_GDEY075T7 panel{44, 10, 38, 4};
  uint8_t previous[48000], current[48000];
  bool valid = false, failed = false, sawBusy = false;
  unsigned partials = 0;
};
