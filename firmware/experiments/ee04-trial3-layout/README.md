# Museum trial3 layout refresh bench

This is an Arduino IDE source kit for the EE04 Museum sign. Extract the ZIP and open Trial3LayoutBench/Trial3LayoutBench.ino. Expect the trial3 Nimbus Sans fonts and normal clock, countdown and smaller labels, with a simulated timetable and battery value. Bench startup bypasses normal network, clock persistence and timetable loading.

Use the same XIAO ESP32S3 Plus settings as working trial3, including the existing partition scheme and Erase All Flash disabled. Dependencies are the original trial3 libraries plus GxEPD2 1.6.9. Restore the sign by reuploading the working trial3 sketch with the same settings.

At 115200 baud with newline:
- On boot, step 0 is a full baseline. Steps 1–4 use differential updates, and step 5 does a full redraw. This repeats through step 15. Automatic updates happen one minute after the last draw.
- Send next to advance immediately. The simulated departure changes on step 4, before the first scheduled cleanup.
- Send diff for a fresh baseline followed by all partials. Take a photo after steps 4 and 5.
- Send hybrid to restart the boot pattern, full for a full-refresh control, or stop to pause automatic updates.
- With the 915 MHz antenna attached, radio repeats hybrid and transmits a diagnostic LoRa packet before each change after baseline.

Compare the small clock and labels from the same angle and in the same light. Save the LAYOUT serial lines for drive and total time. Firmware and optical performance still require a physical bench test.
