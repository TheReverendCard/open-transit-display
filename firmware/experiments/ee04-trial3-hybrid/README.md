# Trial3 differential refresh candidate

This sketch uses the normal trial3 data, clock, display slots and LoRa path. It starts with the existing Seeed full refresh, then establishes a GxEPD2 full baseline on the first scheduled update. Four differential refreshes follow each GxEPD2 full refresh. Both image planes are reloaded on each update to recover from the reset shared with the Wio. A BUSY failure falls back to Seeed full refresh until reboot. Set OTD_ENABLE_DIFFERENTIAL to 0 in the sketch to build in full-refresh-only mode.

The layout bench photographs show readable normal-sized text across the simulated 08:12 to 08:13 updates. The owner reported a substantial speed improvement. These observations do not quantify energy or confirm operation with production LoRa traffic.

Open OTDTrial3Hybrid/OTDTrial3Hybrid.ino. Use the same XIAO ESP32S3 Plus board and partition settings as trial3, with Erase All Flash disabled. Requires the working trial3 libraries and GxEPD2 1.6.9. To revert, upload the working trial3 sketch. Watch serial at 115200 for EPD FULL and EPD DIFF and compare against real LoRa ACKs and timetable rollover. The build and live integration are unverified until compiled and tested.
