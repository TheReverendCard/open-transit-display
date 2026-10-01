#include <Arduino.h>
#include "../../shared/display_policy.h"

// Fail closed until an adapter implements signature verification, scoped key
// provisioning, durable revision storage and trusted UTC. This is a compile
// target and integration seam, not a ready-to-flash public sign application.
void setup() {
  Serial.begin(115200);
  otd::NoticeState state;
  const auto page = otd::page(state, 0);
  Serial.println(page == otd::Page::Transit
    ? "OTD development scaffold: transit fallback; authority/clock/panel unconfigured"
    : "Unexpected state");
}
void loop() { delay(1000); }
