#pragma once
#include <stddef.h>
#include <stdint.h>

// XIAO ESP32-S3 + B2B Wio-SX1262 + Seeed ePaper Driver Board v2.
// Values are ESP32 GPIO numbers, NOT D-label numbers. Header Wio is a different board.
namespace otd::reference_board {
constexpr const char* id = "seeed-xiao-s3-wio-b2b-epaper-v2";
constexpr int spi_sck = 7;   // D8
constexpr int spi_miso = 8;  // D9, radio only
constexpr int spi_mosi = 9;  // D10
constexpr int epaper_rst = 1;   // D0
constexpr int epaper_cs = 2;    // D1
constexpr int epaper_busy = 3;  // D2
constexpr int epaper_dc = 4;    // D3
constexpr int radio_cs = 41;
constexpr int radio_rst = 42;
constexpr int radio_busy = 40;
constexpr int radio_dio1 = 39;
constexpr int radio_rxen = 38;
constexpr float radio_tcxo_volts = 1.8f;
constexpr bool radio_dio2_rf_switch = true;
constexpr int i2c_sda = 5;  // D4, available for RTC/fuel gauge
constexpr int i2c_scl = 6;  // D5
constexpr int spare_tx = 43; // D6
constexpr int spare_rx = 44; // D7
constexpr int battery_adc = -1; // no verified divider on this combination

constexpr int occupied[] = {spi_sck, spi_miso, spi_mosi, epaper_rst, epaper_cs,
  epaper_busy, epaper_dc, radio_cs, radio_rst, radio_busy, radio_dio1, radio_rxen};
constexpr bool pins_unique() {
  for (size_t i = 0; i < sizeof(occupied) / sizeof(occupied[0]); ++i)
    for (size_t j = i + 1; j < sizeof(occupied) / sizeof(occupied[0]); ++j)
      if (occupied[i] == occupied[j]) return false;
  return true;
}
static_assert(pins_unique(), "Reference hardware has conflicting GPIO assignments");
} // namespace otd::reference_board
