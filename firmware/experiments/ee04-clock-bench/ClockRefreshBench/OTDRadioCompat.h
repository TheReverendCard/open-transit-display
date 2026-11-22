#pragma once
#include <RadioLib.h>

// RadioLib 8 removed the individual begin arguments and packet-action aliases.
// Keep OTD's field-tested RX/TX/IRQ call sites intact.  On SX126x the old receive
// aliases attach/detach the rising-edge DIO1 handler; use that same API in v8.
// This adapter deliberately supports the two verified major API families only.
#if RADIOLIB_VERSION_MAJOR != 7 && RADIOLIB_VERSION_MAJOR != 8
#error "OTD requires RadioLib 7.x or 8.x (verified with 7.3.0 and 8.0.0)."
#endif

class OtdSX1262 : public SX1262 {
public:
  OtdSX1262(Module* module) : SX1262(module) {}

  int16_t beginOtdRadio() {
#if RADIOLIB_VERSION_MAJOR >= 8
    ConfigLoRa_t config;
    // v8 integers are Hz, not the MHz/kHz floats used by the v7 overload.
    config.frequency = RADIOLIB_UNIT_MEGA(915);
    config.bandwidth = RADIOLIB_UNIT_KILO(125);
    config.spreadingFactor = 9;
    config.codingRate = 7;
    config.syncWord = 0x12;
    config.power = 10;
    config.preambleLength = 8;
    // These are SX126x members, not fields in ConfigLoRa_t.  Set before begin.
    tcxoVoltage = RadioLibTCXOVoltage_t::Voltage1V8;
    useRegulatorLDO = false;
    return SX1262::begin(config);
#else
    return SX1262::begin(915.0,125.0,9,7,0x12,10,8,1.8);
#endif
  }

#if RADIOLIB_VERSION_MAJOR >= 8
  void setPacketReceivedAction(void (*handler)(void)) { setDio1Action(handler); }
  void clearPacketReceivedAction() { clearDio1Action(); }
#endif
};
