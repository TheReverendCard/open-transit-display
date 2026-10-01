#pragma once
#include <Arduino.h>
#include <SPI.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include "boards/seeed_xiao_s3_wio_epaper.h"

namespace otd {
// One shared SPI instance. Both drivers must use this instance and take this
// mutex for SPI transfers, including transfers on different FreeRTOS tasks.
// No SPI work from ISR; DIO1 ISR must only signal its worker task.
class ReferenceSpi {
 public:
  bool begin() {
    if (mutex_) return true;
    mutex_ = xSemaphoreCreateMutex();
    if (!mutex_) return false;
    // Set output latches high before enabling outputs so neither chip is selected.
    digitalWrite(reference_board::epaper_cs, HIGH);
    digitalWrite(reference_board::radio_cs, HIGH);
    pinMode(reference_board::epaper_cs, OUTPUT);
    pinMode(reference_board::radio_cs, OUTPUT);
    pinMode(reference_board::epaper_busy, INPUT);
    pinMode(reference_board::radio_busy, INPUT);
    pinMode(reference_board::radio_dio1, INPUT);
    SPI.begin(reference_board::spi_sck, reference_board::spi_miso,
              reference_board::spi_mosi, -1);
    return true;
  }
  SPIClass& bus() { return SPI; }
  bool lock(TickType_t timeout = pdMS_TO_TICKS(1000)) {
    return mutex_ && xSemaphoreTake(mutex_, timeout) == pdTRUE;
  }
  void unlock() { xSemaphoreGive(mutex_); }
 private:
  SemaphoreHandle_t mutex_ = nullptr;
};

class SpiGuard {
 public:
  explicit SpiGuard(ReferenceSpi& shared) : shared_(shared), held_(shared.lock()) {}
  ~SpiGuard() { if (held_) shared_.unlock(); }
  explicit operator bool() const { return held_; }
  SpiGuard(const SpiGuard&) = delete;
  SpiGuard& operator=(const SpiGuard&) = delete;
 private:
  ReferenceSpi& shared_;
  bool held_;
};
} // namespace otd
