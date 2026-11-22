// SPDX-License-Identifier: GPL-3.0-or-later
// Standalone EE04 bench sketch. GPIO38 is shared by EPD reset and Wio TX.
#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <GxEPD2.h>
#include <gdey/GxEPD2_750_GDEY075T7.h>
#include "OTDRadioCompat.h"

#if !defined(ARDUINO_XIAO_ESP32S3_Plus) && !defined(ARDUINO_XIAO_ESP32S3_PLUS)
#error "Select Seeed Studio XIAO ESP32S3 Plus (16 MB) for the EE04 sign."
#endif

constexpr int EpdCS = 44, EpdDC = 10, EpdBusy = 4, EpdEnable = 43;
constexpr int SharedReset = 38, RadioCS = 41, Dio1 = 39;
constexpr uint16_t Width = 800, Height = 480;
constexpr uint32_t IntervalMs = 60000;
constexpr unsigned Steps = 12;

GxEPD2_750_GDEY075T7 panel(EpdCS, EpdDC, SharedReset, EpdBusy);
GFXcanvas1 canvas(Width, Height);
OtdSX1262 radio = new Module(RadioCS, Dio1, 42, 40, SPI, SPISettings(2000000, MSBFIRST, SPI_MODE0));
enum class Phase { idle, full, diff, radio };
void beginPhase(Phase selected);
Phase phase = Phase::idle;
bool radioReady = false, listening = false, waiting = false, showingEights = true;
bool panelFault = false, observedBusy = false;
uint32_t due = 0;
unsigned step = 0;

const char* name() {
  switch (phase) {
    case Phase::full: return "full";
    case Phase::diff: return "diff";
    case Phase::radio: return "radio";
    default: return "idle";
  }
}

void render(bool eights) {
  canvas.fillScreen(1);  // GxEPD2 raw 1-bit convention: one is white.
  canvas.setTextColor(0);
  canvas.setTextSize(3);
  canvas.setCursor(32, 32);
  canvas.print("Open Transit Display / clock test");
  canvas.drawRect(16, 16, 768, 448, 0);
  canvas.drawFastHLine(32, 100, 736, 0);
  canvas.fillRect(40, 374, 58, 38, 0);
  canvas.drawRect(109, 374, 58, 38, 0);
  canvas.setCursor(188, 385);
  canvas.setTextSize(2);
  canvas.print("Static contrast and ghosting reference");
  canvas.setTextSize(18);
  canvas.setCursor(139, 167);
  canvas.print(eights ? "08:08" : "11:11");
}

void observeBusy(const void*) { observedBusy = true; delay(1); }

bool refreshFrame(bool nextEights, bool full, bool afterTx) {
  uint32_t start = millis();
  if (afterTx) {
    // The physical glass still shows the previous frame. The controller reset
    // during TX; reinitialize its driver state without forcing a full refresh.
    panel.init(0, false, 10, false);
  }
  // The driver's default differential waveform can scan the whole panel.
  // Restore every reference pixel, including static content outside the clock.
  render(showingEights);
  panel.writeImageToPrevious(canvas.getBuffer(), 0, 0, Width, Height);
  render(nextEights);
  panel.writeImage(canvas.getBuffer(), 0, 0, Width, Height);
  uint32_t driven = millis();
  observedBusy = false;
  panel.refresh(!full);
  uint32_t finished = millis();
  const bool sawBusy = observedBusy;
  // Driver BUSY timeout is 10 s. A timed-out refresh cannot advance the shadow.
  const bool ok = sawBusy && digitalRead(EpdBusy) == HIGH && finished - driven < 10000;
  panel.powerOff();
  Serial.printf("EPD phase=%s step=%u clock=%s waveform=%s tx_before=%d prepare_ms=%lu drive_ms=%lu total_ms=%lu busy_seen=%d result=%s\n",
                name(), step, nextEights ? "08:08" : "11:11", full ? "full" : "differential",
                afterTx, (unsigned long)(driven-start), (unsigned long)(finished-driven),
                (unsigned long)(millis()-start), sawBusy, ok ? "ready" : "fault");
  if (ok) showingEights = nextEights;
  return ok;
}

void stopPhase() {
  if (radioReady) radio.standby();
  digitalWrite(SharedReset, HIGH);
  listening = waiting = false;
  phase = Phase::idle;
}

bool startListen() {
  int16_t status = radio.startReceive();
  listening = status == RADIOLIB_ERR_NONE;
  if (!listening) { Serial.printf("RX error=%d\n", status); stopPhase(); }
  return listening;
}

void beginPhase(Phase selected) {
  stopPhase();
  if (panelFault) { Serial.println("Reset the board after checking BUSY and the panel connection."); return; }
  if (selected == Phase::radio && !radioReady) {
    int16_t status = radio.beginOtdRadio();
    if (status == RADIOLIB_ERR_NONE) status = radio.setDio2AsRfSwitch(true);
    if (status != RADIOLIB_ERR_NONE) { Serial.printf("Wio init error=%d\n", status); return; }
    radioReady = true;
  }
  phase = selected;
  step = 0;
  // Establish the same clean starting image for each comparison.
  panelFault = !refreshFrame(true, true, false);
  if (panelFault) { stopPhase(); return; }
  due = millis() + IntervalMs;
  Serial.printf("START %s: 12 changes, one per minute. 'next' brings the next change forward.\n", name());
  if (phase == Phase::radio) Serial.println("Each change waits for an OTD1/2/3 or OTDXQ1 packet. 'probe' substitutes a local test transmission.");
}

void advance(bool afterTx) {
  ++step;
  panelFault = !refreshFrame(!showingEights, phase == Phase::full, afterTx);
  if (panelFault || step == Steps) {
    Serial.println(panelFault ? "HALTED: display state uncertain." : "DONE: inspect the digits and reference before starting another phase.");
    stopPhase();
  } else {
    waiting = false;
    due = millis() + IntervalMs;
  }
}

void nextChange() {
  if (phase == Phase::idle) return;
  if (phase != Phase::radio) { advance(false); return; }
  if (!waiting && startListen()) {
    waiting = true;
    Serial.println("WAIT for next gateway frame, or send 'probe' with the antenna attached.");
  }
}

void transmitThenDraw(bool replying) {
  int16_t status = radio.standby();
  listening = false;
  if (status != RADIOLIB_ERR_NONE) { Serial.printf("Standby error=%d\n", status); stopPhase(); return; }
  digitalWrite(EpdCS, HIGH);
  digitalWrite(SharedReset, LOW);
  delay(10);
  String packet = String(replying ? "OTDXA1|EINK|" : "OTDXP1|EINK|") + (step + 1);
  status = radio.transmit(packet);
  digitalWrite(SharedReset, HIGH);
  delay(10);
  Serial.printf("TX kind=%s status=%d\n", replying ? "diagnostic_ack" : "local_probe", status);
  if (status != RADIOLIB_ERR_NONE) { stopPhase(); return; }
  advance(true);
}

void readRadio() {
  if (!listening || !digitalRead(Dio1)) return;
  String packet;
  const int16_t status = radio.readData(packet);
  listening = false;
  if (status == RADIOLIB_ERR_NONE &&
      (packet.startsWith("OTD1|") || packet.startsWith("OTD2|") ||
       packet.startsWith("OTD3|") || packet.startsWith("OTDXQ1|"))) {
    transmitThenDraw(true);
  } else {
    startListen();
  }
}

void handle(const char* command) {
  if (!strcmp(command, "diff")) beginPhase(Phase::diff);
  else if (!strcmp(command, "full")) beginPhase(Phase::full);
  else if (!strcmp(command, "radio")) beginPhase(Phase::radio);
  else if (!strcmp(command, "next")) nextChange();
  else if (!strcmp(command, "probe") && phase == Phase::radio) transmitThenDraw(false);
  else if (!strcmp(command, "stop")) stopPhase();
  else if (!strcmp(command, "status")) Serial.printf("STATUS phase=%s step=%u/%u waiting=%d fault=%d\n", name(), step, Steps, waiting, panelFault);
  else Serial.println("Commands: diff | full | radio | next | probe | stop | status");
}

void setup() {
  Serial.begin(115200);
  pinMode(RadioCS, OUTPUT); digitalWrite(RadioCS, HIGH);
  pinMode(EpdCS, OUTPUT); digitalWrite(EpdCS, HIGH);
  pinMode(SharedReset, OUTPUT); digitalWrite(SharedReset, HIGH);
  pinMode(EpdEnable, OUTPUT); digitalWrite(EpdEnable, HIGH);
  delay(100);
  SPI.begin(7, 8, 9, -1);
  panel.selectSPI(SPI, SPISettings(4000000, MSBFIRST, SPI_MODE0));
  panel.init(0, true, 10, false);
  panel.setBusyCallback(observeBusy);
  if (!canvas.getBuffer()) { panelFault = true; Serial.println("No RAM for the 48000-byte display buffer."); return; }
  Serial.println("OTD clock bench v1. 'help' lists commands. Attach the 915 MHz antenna before 'radio'.");
  beginPhase(Phase::diff);
}

void loop() {
  static char line[24];
  static size_t length = 0;
  while (Serial.available()) {
    int c = Serial.read();
    if (c == '\r' || c == '\n') {
      if (length) { line[length] = 0; handle(line); length = 0; }
    } else if (length < sizeof(line)-1 && c >= 32 && c <= 126) line[length++] = char(c);
  }
  if (phase != Phase::idle && !waiting && (int32_t)(millis() - due) >= 0) nextChange();
  readRadio();
  delay(2);
}
