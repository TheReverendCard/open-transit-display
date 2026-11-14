# Museum sign v0.8.4c outline typography trial

13 November 2026. The owner firmware package OTD_v084c_Outline.zip builds directly in Arduino IDE. It embeds the original project Nimbus Sans Regular and Bold OTF data (165,528 bytes combined) and stb_truetype v1.28 (revision 9600522de53973336fa033a289858a4354cbb04c). All passenger text uses the same outline renderer. The older route font generation step is superseded for this Museum sketch. The reference preview is an 800 × 480 monochrome host rendering.

The display measures UTF-8 strings against the existing region, rasterises fitted glyphs individually at the final scale and paints black spans into the Seeed framebuffer. It uses a coverage threshold of 112/255. The original 854-character Unicode mapping per face includes Māori macrons. The presentation layer maps the Museum's ASCII stop name to Whangārei Museum. The LoRa protocol, timetable, light sleep and v0.8.4b provisional clock logic carry forward.

## Verification

Arduino-ESP32 3.3.5, XIAO_ESP32S3_Plus, OPI PSRAM, CDC on boot enabled, default 2 MiB application partition. Seeed_GFX 2.0.3 (0dfdd71), RadioLib 7.4.0 and ArduinoJson 7.4.2. With identical settings, v0.8.4b used 1,941,347 program bytes and 50,236 static RAM bytes. The v0.8.4c build used 1,414,051 program bytes and 50,556 static RAM bytes. The saving is 527,296 program bytes (27.2%). The existing radio initialisation targets RadioLib 7.x. A trial build using RadioLib 8.0.0 hit removed radio APIs.

Host checks passed for 24 render samples including estimated clock, multi-character route, timetable statuses and macrons. All drawn spans stayed in bounds. The clock helper passed 21 assertions and 17 applicable firmware invariants passed.

## Field check

Upload the complete extracted sketch with Erase All Flash off. Confirm the startup version, compare the physical screen with the included preview, watch a minute refresh and confirm the gateway receives an ACK. The NIMBUS serial line reports framebuffer draw milliseconds and the heap low-water mark since boot. Panel appearance, board timing, runtime heap and battery endurance await field testing. To roll back, re-upload the previous working sketch with its existing headers.