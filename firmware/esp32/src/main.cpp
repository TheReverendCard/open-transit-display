#include <Arduino.h>
#include "../../shared/display_policy.h"
#ifdef OTD_REFERENCE_XIAO_WIO_EPAPER
#include "reference_spi.h"
otd::ReferenceSpi shared_spi;
#endif

// Fail closed until an adapter implements signature verification, scoped key
// provisioning, durable revision storage and trusted UTC. This is a compile
// target and integration seam, not a ready-to-flash public sign application.
void setup() {
  Serial.begin(115200);
#ifdef OTD_REFERENCE_XIAO_WIO_EPAPER
  const uint32_t serial_started = millis();
  while (!Serial && millis() - serial_started < 2000) delay(10);
  Serial.printf("Reference board: %s\n", otd::reference_board::id);
  if (!shared_spi.begin()) {
    Serial.println("Shared SPI unavailable; device drivers remain disabled");
    return;
  }
  Serial.println("Shared SPI ready; display CS=GPIO2, radio CS=GPIO41");
  Serial.println("Panel: Seeed 104990861; integrated display/mesh drivers pending; radio disabled");
#endif
  otd::NoticeState state;
  const auto page = otd::page(state, 0);
  Serial.println(page == otd::Page::Transit
    ? "OTD development scaffold: transit fallback; authority/clock/panel unconfigured"
    : "Unexpected state");
}
void loop() { delay(1000); }
