/*
  Open Transit Display: UC8179 7.5-inch e-paper refresh benchmark v0.1
  Seeed EE04 + XIAO ESP32-S3 Plus, Wio-SX1262 may remain fitted.

  Standalone display experiment: this sketch does NOT initialise LoRa.
  Use Arduino IDE with Seeed_GFX, XIAO_ESP32S3_PLUS, OPI PSRAM,
  USB CDC On Boot ENABLED and the included driver.h.

  It does not change the PC LoRa sender or gateway.
  Test results are not proof that partial refresh is safe for all UC8179 panels.
*/
#include <Arduino.h>
#include <TFT_eSPI.h>
#include <string.h>
#include "ExperimentTypes.h"  // Avoid Arduino auto-prototype errors.

static constexpr uint8_t RADIO_CHIP_SELECT = 41;
static constexpr uint16_t PANEL_W = 800;
static constexpr uint16_t PANEL_H = 480;
static constexpr size_t IMAGE_BYTES = (size_t)PANEL_W * PANEL_H / 8;
static constexpr Rect TIME_AREA = {168, 165, 464, 135};
static constexpr uint8_t STEPS_PER_MODE = 12;
static constexpr uint32_t STEP_INTERVAL_MS = 15000;

EPaper panel;
uint8_t *previousFrame = nullptr;
TestMode currentMode = ONE_PASS;
uint8_t stepNumber = 0;
uint32_t lastUpdateAt = 0;
bool paused = false;
bool finished = false;
const char* currentClock = "10:29";

const char* modeName(TestMode mode) {
  switch (mode) {
    case ONE_PASS: return "A: one partial refresh";
    case ERASE_REDRAW: return "B: erase then draw";
    case DIRTY_RECT: return "C: dirty pixel rectangle";
    case FULL_ONLY: return "D: full refresh control";
  }
  return "Unknown";
}

void radioSafeSelect() {
  // The Wio is connected physically, but never transmits or receives in this test.
  // Keep its SPI chip-select inactive so the display exclusively owns SPI.
  pinMode(RADIO_CHIP_SELECT, OUTPUT);
  digitalWrite(RADIO_CHIP_SELECT, HIGH);
}

void restoreRFswitch() {
  // GPIO38 is display RST as well as the attached Wio RF switch.
  // This test DOES NOT configure a radio; keep line high after refresh.
  pinMode(38, OUTPUT);
  digitalWrite(38, HIGH);
}

void drawClock(const char* value) {
  panel.fillRect(TIME_AREA.x, TIME_AREA.y, TIME_AREA.w, TIME_AREA.h, TFT_WHITE);
  panel.setTextColor(TFT_BLACK, TFT_WHITE);
  panel.setTextSize(3);
  panel.setTextDatum(MC_DATUM);
  panel.drawString(value, 400, 233, 4);
  panel.setTextSize(1);
}

void drawBaseline() {
  panel.fillScreen(TFT_WHITE);
  panel.drawRect(2, 2, 796, 476, TFT_BLACK);
  panel.drawRect(5, 5, 790, 470, TFT_BLACK);
  panel.setTextColor(TFT_BLACK, TFT_WHITE);
  panel.setTextSize(1);
  panel.setTextDatum(TC_DATUM);
  panel.drawString("OPEN TRANSIT DISPLAY  /  UC8179 REFRESH TEST", 400, 23, 2);
  panel.drawString(modeName(currentMode), 400, 91, 4);
  panel.drawRect(163, 160, 474, 145, TFT_BLACK);
  panel.setTextDatum(MC_DATUM);
  panel.drawString("Compare old-digit ghosts inside this border", 400, 348, 2);
  panel.drawString("12 changes at 15-second intervals / USB Serial for results", 400, 403, 2);
  drawClock("10:29");
  currentClock = "10:29";
}

uint32_t doFull() {
  radioSafeSelect();
  const uint32_t began = millis();
  panel.update();
  restoreRFswitch();
  return millis() - began;
}

uint32_t doPartial(Rect r) {
  // Seeed_GFX API spelling really is updataPartial().
  radioSafeSelect();
  const uint32_t began = millis();
  panel.updataPartial(r.x, r.y, r.w, r.h);
  restoreRFswitch();
  return millis() - began;
}

void saveFrame() {
  if (previousFrame) {
    const void* ptr = panel.getPointer();
    if (ptr) memcpy(previousFrame, ptr, IMAGE_BYTES);
  }
}

// Compare the previous and current 1-bit framebuffers, byte by byte.
// No assumptions about which bit corresponds to the leftmost pixel are needed.
// Result is an 8-pixel-aligned bounding rectangle with a small safety margin.
Rect dirtyBounds(const Rect &region, uint32_t &changedBytes, uint32_t &changedBits) {
  changedBytes = 0;
  changedBits = 0;
  if (!previousFrame || !panel.getPointer()) return region;
  const auto* now = static_cast<const uint8_t*>(panel.getPointer());
  const int stride = PANEL_W / 8;
  int minByte = PANEL_W / 8, maxByte = -1;
  int minRow = PANEL_H, maxRow = -1;
  for (int y = region.y; y < region.y + region.h; y++) {
    for (int col = region.x / 8; col < (region.x + region.w + 7) / 8; col++) {
      const uint8_t diff = now[y * stride + col] ^ previousFrame[y * stride + col];
      if (!diff) continue;
      changedBytes++;
      changedBits += __builtin_popcount((unsigned)diff);
      if (col < minByte) minByte = col;
      if (col > maxByte) maxByte = col;
      if (y < minRow) minRow = y;
      if (y > maxRow) maxRow = y;
    }
  }
  if (maxByte < minByte) return {0, 0, 0, 0};
  minByte = max(0, minByte - 1);
  maxByte = min(PANEL_W / 8 - 1, maxByte + 1);
  minRow = max(0, minRow - 4);
  maxRow = min((int)PANEL_H - 1, maxRow + 4);
  return {(int16_t)(minByte * 8), (int16_t)minRow,
          (int16_t)((maxByte - minByte + 1) * 8),
          (int16_t)(maxRow - minRow + 1)};
}

void startMode(TestMode mode) {
  currentMode = mode;
  finished = false;
  stepNumber = 0;
  Serial.printf("\nMODE %s\n", modeName(mode));
  Serial.println("Clean white full-screen refresh, then reference image.");
  panel.fillScreen(TFT_WHITE);
  const uint32_t clearTime = doFull();
  drawBaseline();
  const uint32_t baselineTime = doFull();
  saveFrame();
  lastUpdateAt = millis();
  Serial.printf("CLEAN %lu ms; BASELINE %lu ms; first sample in 15 seconds.\n",
                (unsigned long)clearTime, (unsigned long)baselineTime);
}

void runOneStep() {
  if (finished || paused) return;
  ++stepNumber;
  const char* newText = (stepNumber & 1) ? "10:30" : "10:29";
  uint32_t eraseMs = 0;
  uint32_t drawMs = 0;
  uint32_t dirtyBytes = 0;
  uint32_t dirtyBits = 0;
  Rect region = TIME_AREA;

  if (currentMode == ERASE_REDRAW) {
    panel.fillRect(TIME_AREA.x, TIME_AREA.y, TIME_AREA.w, TIME_AREA.h, TFT_WHITE);
    eraseMs = doPartial(TIME_AREA);  // Explicit white pass.
    drawClock(newText);
    drawMs = doPartial(TIME_AREA);
  } else {
    drawClock(newText);
    if (currentMode == ONE_PASS) drawMs = doPartial(TIME_AREA);
    else if (currentMode == DIRTY_RECT) {
      region = dirtyBounds(TIME_AREA, dirtyBytes, dirtyBits);
      if (region.w > 0 && region.h > 0) drawMs = doPartial(region);
    } else if (currentMode == FULL_ONLY) drawMs = doFull();
  }
  currentClock = newText;
  saveFrame();
  Serial.printf("%s step=%u/12 value=%s window=[%d,%d,%d,%d] "
                "changed_bytes=%lu changed_bits=%lu erase_ms=%lu draw_ms=%lu total_ms=%lu\n",
                modeName(currentMode), (unsigned)stepNumber, currentClock,
                region.x,region.y,region.w,region.h,
                (unsigned long)dirtyBytes,(unsigned long)dirtyBits,
                (unsigned long)eraseMs,(unsigned long)drawMs,
                (unsigned long)(eraseMs+drawMs));
  lastUpdateAt = millis();
  if (stepNumber >= STEPS_PER_MODE) {
    if (currentMode == FULL_ONLY) {
      finished = true;
      Serial.println("ALL METHODS COMPLETE. Screen left showing final control frame.");
      Serial.println("Send a/b/c/f to repeat a method, or r to restart all.");
    } else {
      Serial.println("Method complete; switching after 20 seconds. Photograph the screen now.");
      delay(20000);
      startMode(static_cast<TestMode>(static_cast<uint8_t>(currentMode)+1));
    }
  }
}

void help() {
  Serial.println("Commands: a=one partial, b=erase/redraw, c=dirty region, f=full control,");
  Serial.println("n=next mode, r=restart, p=pause/resume, q=pause, h=help.");
  Serial.println("Auto sequence: A->B->C->D, 12 changes/mode, 15 s between changes.");
  Serial.println("For an equal comparison, the device starts each method with two full updates.");
}

void handleCommand(char c) {
  switch (c) {
    case 'a': startMode(ONE_PASS); paused=false; break;
    case 'b': startMode(ERASE_REDRAW); paused=false; break;
    case 'c': startMode(DIRTY_RECT); paused=false; break;
    case 'f': startMode(FULL_ONLY); paused=false; break;
    case 'n': startMode(static_cast<TestMode>((static_cast<int>(currentMode)+1)%4));paused=false;break;
    case 'r': startMode(ONE_PASS);paused=false;break;
    case 'p': paused=!paused;lastUpdateAt=millis();Serial.printf("PAUSED=%d\n",paused);break;
    case 'q': paused=true;Serial.println("PAUSED");break;
    case 'h': help();break;
  }
}

void setup() {
  Serial.begin(115200);
  delay(1200);
  radioSafeSelect();
  Serial.println("UC8179 e-paper refresh experiment v0.1");
  panel.begin();
  panel.setRotation(0);
  if (panel.width()!=PANEL_W || panel.height()!=PANEL_H || panel.getColorDepth()!=1) {
    Serial.printf("UNSUPPORTED BUFFER width=%d height=%d bpp=%d; HALTING\n",
      panel.width(),panel.height(),panel.getColorDepth());
    while (true) delay(1000);
  }
  if (!panel.getPointer()) {
    Serial.println("EPD backing sprite is null; HALTING");
    while (true) delay(1000);
  }
  previousFrame = static_cast<uint8_t*>(malloc(IMAGE_BYTES));
  if (!previousFrame) Serial.println("WARNING: cannot allocate 48 KB previous frame; method C falls back to full region.");
  help();
  startMode(ONE_PASS);
}

void loop() {
  while (Serial.available()) {
    char c = static_cast<char>(Serial.read());
    if (c >= 'A' && c <= 'Z') c = c - 'A' + 'a';
    handleCommand(c);
  }
  if (!paused && !finished && millis() - lastUpdateAt >= STEP_INTERVAL_MS) runOneStep();
  delay(40);
}