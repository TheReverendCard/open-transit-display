# Museum EE04 differential clock trial 1

[Download the Windows bench kit](../packages/ee04-clock-bench/OTD_Clock_Refresh_Bench.zip) or read the [operating instructions and source](../firmware/experiments/ee04-clock-bench/README.md).

The standalone application and its reversible installer are ready for an owner-run bench trial.  The XIAO ESP32-S3 Plus build passed, and five simulated-flash tests passed, including interrupted installation and byte-for-byte restoration.  The prepared package was checked against the compiled binary and all of its ZIP entries passed CRC checks.  The setup targets the existing Museum sign partition layout and checks the connected node identity.  See the physical panel result below. Radio delivery and restoration on the actual device remain unverified.

- [Verified Arduino build and tests](https://github.com/TheReverendCard/open-transit-display/actions/runs/45080622668)
- Source revision `19885d6770ac23499af2c6b71c62ef1ca6a5421d`
- Application binary 348896 bytes, SHA-256 `f641b870dc671b5eb9a70e0eb1f9113491d565cb69811300bc070f201705f5af`
- Downloadable ZIP 220137 bytes, SHA-256 `a56e953d4317914aaa3028a3e553032f24a82eb6aee7bc31ddf3f2fdd78c23b6`

The field firmware remains trial3.  This bench application lives on a separate branch and is loaded only when the operator runs Install_Bench.cmd.  Restore_Sign.cmd writes back the sectors saved from that specific sign.  For the bench result, record the phase and transition, drive and total times, whether previous strokes remain visible, and whether a genuine or self-initiated LoRa transmission preceded the redraw.

A second offline check seeded a 16 MiB flash fixture with the locally compiled Museum trial3 application, its actual partition table and its OTA selection image.  Installing the exact downloadable binary and then restoring it reproduced the complete starting flash byte for byte.  Esptool 5.3.1 recognized the packaged application as an ESP32-S3 image and validated both its image checksum and embedded SHA-256.


## Physical panel result, 23 November 2026

The owner completed all 12 differential changes on the Museum panel. They described it as substantially faster than the earlier methods and reasonably good through about five changes. The final photograph shows a readable 08:08 with uneven darkness between segments. The static test block is also visibly grey in the photograph. A matched baseline photograph and serial timings were not supplied, so neither cumulative contrast loss in the static block nor refresh latency is quantified. The installer hit a Windows COM3 access-denied error before any flash write. The upload method and radio phase were not independently verified.

For the next comparison, use the trial3 renderer, normal font sizes and real clock and countdown positions. Compare a full baseline with four and five differential changes, then repeat periodic full cleanup over several cycles. Include changing thin strokes, static labels and the transition to a new departure. Photograph each checkpoint under consistent lighting, and log drive and total times. Compare the same sequence with Wio transmissions before an update to test shared reset recovery. Let the smallest passenger-facing text determine the refresh cadence.
