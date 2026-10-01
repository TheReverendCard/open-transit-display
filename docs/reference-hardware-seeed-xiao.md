# Reference hardware: XIAO ESP32-S3, B2B Wio-SX1262, Seeed ePaper Driver Board v2

This is the preferred hardware profile for the first transit display. It uses the
Wio-SX1262 version connected to the XIAO ESP32-S3's board-to-board (B2B) socket.
The header-connected Wio expansion is a different wiring arrangement and must not
be substituted under this profile. Electrical pin compatibility is documented;
the complete mechanical stack and panel operation have not been tested here.

## Pin allocation

All firmware constants are ESP32 GPIO numbers, not XIAO D numbers.

| Function | XIAO label | ESP32-S3 GPIO |
| --- | --- | --- |
| Shared SPI clock | D8 | 7 |
| Shared SPI MOSI | D10 | 9 |
| Radio SPI MISO | D9 | 8 |
| ePaper reset | D0 | 1 |
| ePaper chip select | D1 | 2 |
| ePaper busy | D2 | 3 |
| ePaper data/command | D3 | 4 |
| Radio chip select | B2B | 41 |
| Radio reset | B2B | 42 |
| Radio busy | B2B | 40 |
| Radio DIO1 interrupt | B2B | 39 |
| Radio RX enable | B2B | 38 |
| Available I2C SDA/SCL | D4/D5 | 5/6 |
| Available serial/general IO | D6/D7 | 43/44 |

The display and radio share clock/MOSI but have separate chip-select, reset and
busy lines. No conflicting control pins appear in this mapping. The Wio module
uses the camera expansion connector, so the XIAO Sense camera expansion cannot
occupy that connector at the same time. Do not solder common stacking headers
through Wio control pads as if they were XIAO D0-D4 passthrough pins; check the
module schematic and actual assembly first.

## Firmware support in this branch

`pio run -d firmware/esp32 -e xiao_s3_wio_epaper` builds the dedicated reference
target using PlatformIO's `seeed_xiao_esp32s3` board definition. That definition
provides 8 MB flash settings, PSRAM support and native USB CDC. The profile is now
the default ESP32 build target and is included in the GitHub compile matrix.

`include/boards/seeed_xiao_s3_wio_epaper.h` owns the GPIO constants and a compile-time
conflict check. `include/reference_spi.h` starts one SPI bus, deselects both chips
before bus startup and supplies a FreeRTOS mutex plus a scoped guard. The startup
diagnostic reports the profile and bus readiness over USB serial. It does not
initialise a guessed panel driver or transmit radio packets.

Both eventual drivers must use that same bus and mutex. Lock only SPI work, not
the entire seconds-long ePaper refresh/BUSY wait. Keep the panel CS inactive while
waiting, allowing radio work between transfers. Radio interrupts only signal a
worker; do not perform SPI or rendering in an ISR. Each driver must use its own
SPI transaction settings. Test radio reception during full and partial refresh.

Use upstream SX1262 settings for the B2B module: DIO3 TCXO supply 1.8 V, DIO2 RF
switch control, and RX enable GPIO38. Do not treat the SX1262's DIO2 as a spare
ESP32 pin. Region, frequency, modem preset, power and antenna must be explicitly
configured before radio activation. Meshtastic and MeshCore remain separate
integration targets; a RadioLib pin definition alone implements neither protocol.

## Panel selection

The ePaper carrier is not the panel. Its FPC connector supports several controller
types and resolutions. Keep `panel_model` unset until the screen's printed model
or product link is known. For the planned 7.5-inch 800x480 monochrome screen, a
one-bit framebuffer is 48,000 bytes; this is a layout-size calculation, not proof
of controller compatibility. Tri-colour and different panel revisions need their
own driver and refresh policy even when dimensions match.

The manufacturer now documents Seeed_GFX with a generated `BOARD_SCREEN_COMBO`
and `USE_XIAO_EPAPER_BREAKOUT_BOARD`. GxEPD2 remains an alternative after matching
the exact controller. Do not hard-code the wiki's 2.9-inch example into this
7.5-inch reference design. The website should select the hardware profile and
then the supported panel, with mesh protocol/features as subsequent options.

## Power and assembly checks

Use the carrier's documented battery connector and power path. Verify connector
polarity, battery specification and physical socket clearance on the actual
assembly. The carrier's published schematic has a charger/boost circuit; that
does not establish a complete solar input controller or measured state of charge.
No battery ADC divider has been verified for this combination, so the firmware
profile reports no battery reading rather than an invented percentage. An I2C
fuel gauge on D4/D5 is the preferred later addition; those pins can also support
a compatible backed RTC for offline expiry.

The Wio unit's physical clearance, antenna routing, enclosure and carrier socket
height still need inspection. Mains-powered development comes first. Before a
solar release, measure the complete assembly's sleep, receive and refresh draw,
including the carrier's boost circuit, and test low-battery/expiry redraw.

## Source references

- [Seeed ePaper Driver Board v2 and ePaper pin assignments](https://wiki.seeedstudio.com/xiao_eink_expansion_board_v2/)
- [Carrier schematic](https://files.seeedstudio.com/wiki/xiao_075inch_epaper_panel/ePaper_Driver_Board.pdf)
- [Seeed ESP32-S3/Wio B2B kit](https://wiki.seeedstudio.com/xiao_esp32s3_%26_wio_SX1262_kit_for_meshtastic/)
- [Wio schematic](https://files.seeedstudio.com/products/SenseCAP/Wio_SX1262/Schematic_Diagram_Wio-SX1262_for_XIAO.pdf)
- [Wio module datasheet](https://files.seeedstudio.com/products/SenseCAP/Wio_SX1262/Wio-SX1262_Module_Datasheet.pdf)
- [Meshtastic upstream B2B pin definitions](https://github.com/meshtastic/firmware/blob/develop/variants/esp32s3/seeed_xiao_s3/variant.h)
- [PlatformIO XIAO ESP32-S3 target](https://docs.platformio.org/en/latest/boards/espressif32/seeed_xiao_esp32s3.html)

Next step: confirm the exact panel, integrate its driver, then perform a USB-powered
panel/radio coexistence test before enabling signed notice reception on hardware.
