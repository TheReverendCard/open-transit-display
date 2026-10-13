# UC8179 refresh experiment v0.1

**Status:** Hardware experiment, not production firmware. Separate from the currently working Museum v0.3.1 diagnostic image.

## Hardware and setup
- Seeed XIAO ESP32-S3 Plus, EE04 e-paper display board with UC8179 800x480 panel and optional physically stacked Wio-SX1262.
- Libraries: Seeed_GFX. In Arduino: XIAO_ESP32S3_PLUS; OPI PSRAM; USB CDC On Boot enabled. 115200 baud serial.
- This sketch does **not** initialise or use LoRa. The sender and gateway do not require reflashing.

## Four methods
1. **A one-pass partial:** clear old text in RAM sprite, draw new text, one updataPartial over fixed clock region.
2. **B white erase and redraw:** issue a blank partial update, then a second partial update with the new value.
3. **C pixel-difference rectangle:** compare previous/current 1-bit sprite images, find changed bytes within clock region, pad and align to 8px, update only dirty rectangle. This does not itself cure ghosting if panel waveforms/old image state are wrong.
4. **D full update:** full-screen refresh control.

Each mode starts with two full updates (white then labelled baseline), performs 12 changes spaced 15 seconds apart, and prints elapsed durations and changed-pixel statistics. It stops when D completes. Commands: a/b/c/f choose mode, n next, r restart, p pause toggle, q pause, h help.

## Cautions
- Test on USB. This is not a battery endurance test.
- Seeed_GFX on this board has severe ghosting with repeated partial updates. White-erase and dirty-region methods are experiments, not fixes guaranteed by the UC8179 controller.
- Wio can stay physically attached, but GPIO38 is shared by e-paper reset and Wio RF switch. Wio CS remains inactive during this sketch.
- Use the v0.3.1 Museum display code again after the test to restore bus-sign functionality.
- This experiment uses temporary built-in fonts so rendering changes do not confound refresh testing. Nimbus Sans is maintained by website/layout workstream.

Follow up results in issue #7. A successful screenshot does not establish production suitability.
