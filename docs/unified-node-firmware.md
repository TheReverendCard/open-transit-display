# Unified node firmware

## Direction agreed 14 November 2026

Develop one firmware for supported node configurations.  Display, gateway and relay are duties that a device can combine or suspend at runtime.  The standalone gateway timetable trial proposed in issue #10 becomes the first gateway test of this shared firmware.  This document records the design direction.  The adaptive duties and policies below are proposed work.  The Museum sign running v0.8.4e is the field baseline.

| Available resources | Eligible duties |
| --- | --- |
| Sustained power, working Wi-Fi upstream, LoRa | Fetch transit updates and coordinate their distribution to the group. |
| The above plus a display | Also show departures for the configured stop. |
| Sustainable solar and battery, LoRa, no working upstream | Receive and, if needed, relay updates within the configured group.  A fitted display serves its stop. |
| Limited battery, LoRa | Prefer receiving updates for the local stop.  Reduce radio activity, suspend routine forwarding and use the cached timetable between updates. |
| Display, no usable network | Show the cached timetable when the clock and schedule coverage allow it.  Indicate when the time is provisional. |

## Setup and duty changes

Use a supported board profile to select safe peripheral pins.  Probe what can be detected reliably.  Ask once for ambiguous hardware or installation details, including power arrangement, display model if needed, Wi-Fi credentials, transit group and local stop if applicable.  Retain those settings across restarts.  Report the detected capabilities, current duties and the reason for each change.

## Solar operating policy

The working goal is for a modest panel and the existing 2,000 mAh class battery to support a stop and scheduled forwarding through ordinary nights.  The Museum light-sleep trial covered about 7 days 19 hours from boot to the last displayed time on a roughly hourly service, with regular radio traffic and acknowledgements.  One diagnostic reported 95.5% of uptime asleep.  This gives us a comparison for measuring added relay and Wi-Fi work.  Panel yield, usable cell capacity and the energy cost on a busy corridor still need measurement.  [Museum endurance record](https://github.com/TheReverendCard/open-transit-display/issues/10#issuecomment-6643382224)

* A commissioned solar stop with adequate reserve should try its assigned forwarding windows.  Record comparable battery readings during existing wakes and summarise them hourly.  An ordinary evening decline is expected.  A single declining hour leaves the forwarding assignment in place.
* Compare the reserve before dawn and the subsequent daytime recharge across several day/night cycles.  Treat voltage as a trend indicator when it is the only measurement.  If the reserve is persistently eroding or the measured discharge suggests it cannot reach the next recharge with margin, reduce background transfers, then widen routine windows or hand forwarding to a suitable neighbour.  Preserve imminent arrivals and local timetable service.  At a genuinely low reserve the node can protect itself immediately, even if it cannot notify the coordinator.
* Restore duties after sustained recovery.  Keep Wi-Fi acquisition, mesh forwarding and display work separately measurable so each installation can carry the duties its power budget supports.  Determine thresholds from the battery, panel, site and traffic trial.  Detect USB power where the board supports it or accept an installer setting.

## Connectivity and passenger service

Treat upstream reachability, feed freshness and radio connectivity separately.  On upstream loss, preserve the age and source of cached departures and continue to serve them within their validity periods.  Keep passenger display cadence independent of network cadence.  Preserve light sleep, wake before first service, provisional clock recovery and existing schedule fallback.

## Stop-to-stop forwarding and radio windows

A group is a set of stops that can exchange relevant transit data over LoRa, including when no internet gateway is reachable.  Any capable sign can forward for another stop.  One Wi-Fi gateway can inject fresh data for the entire corridor.  With the gateway absent, peers can still exchange cached timetable revisions and unexpired predictions with their original timestamps.  Transit area and route scope limit which traffic should cross a link.  Expected device count informs capacity planning.

Start with fixed forwarding assignments based on measured reception.  Where one broadcast reaches several stops, let all consume it and select only the sign needed to reach the next uncovered stops.  Prefer the path expected to use the least airtime including retries.  Reuse assignments until repeated delivery failures or a power change justify repair.  Identify updates by origin and sequence, suppress duplicates, and enforce expiry and a hop limit.

Use a repeating timetable of radio windows that persists across gateway loss.  The upstream sign sends first, with each downstream forwarding slot following its receive slot in the same cycle.  Reserve a short, bounded repair window.  Use guard time for measured clock drift and an infrequent rendezvous window for startup or missed synchronisation.  Peers can maintain relative slot timing while the gateway is away.  Treat passenger clock accuracy separately.  Sleep the radio and processor between required windows where display work permits.

* Live service: send a compact trip update with the source time and affected stops' predictions.  Include a vehicle position once per update if needed.  Generate countdowns locally.  Send on a material prediction or service-state change and at a bounded freshness interval while the source remains live.  Discard superseded updates before forwarding.
* Timetable: advertise revision and coverage in a normal window.  Transfer changed or missing pages in spare slots.  Coalesce missing-page requests, cap retries, and activate a revision after all required pages validate.  Keep serving the previous valid schedule during repair.
* Health: piggyback delivery progress and capability changes where possible.  Avoid per-stop acknowledgements for every group broadcast.  Keep quiet periods sparse and retain the independent first-service wake.

Choose slot lengths and cadence from measured packet airtime, clock drift, processing time, delivery reliability and the acceptable age at the furthest stop.  Record transmissions per delivered update, age at the last stop, missed updates and radio awake time.  A single lost packet should be recoverable within a bounded window without redistributing the whole timetable.  This design uses MeshCore as a reference for peer communication.  Selection of a wire protocol and interoperability remain open.

## Receiver and gateway coordination

**Delivery goal.**  One internet-connected receiver/gateway should serve a corridor of stops from the shared transit feed.  Each stop should get the correct live arrivals when available, keep its validated timetable, and wake only for the work it has accepted.  A display-equipped gateway can serve its own stop at the same time.  Progress and the next bench checks are tracked here.

Today the field setup has a Windows gateway process selecting stop data and submitting packets to the LoRa radio over serial.  The radio reports transmissions and received frames, including acknowledgements.  The Museum sign has demonstrated local timetable fallback and light sleep.  The coordinator described below is a development target.  Treat coordination as a duty in the unified firmware and stage the receiver-side work while the current PC gateway supplies data for comparison.  The earlier standalone proposal and field results are in [issue #10](https://github.com/TheReverendCard/open-transit-display/issues/10).

| Decision | Coordinator responsibility | Stop or forwarding node responsibility |
| --- | --- | --- |
| Group membership and coverage | Start with the installed agency, route, direction and stops.  Reconcile configured stops with reports of stop ID, capabilities and reachable neighbours.  Retain quiet members through sleep.  Review a split when measured airtime or last-stop update age exceeds budget. | Report on joining or when something changes.  A node can hear and forward for a peer without internet access. |
| Upstream selection | Maintain the union of the group's stop, route and direction subscriptions.  Reuse the shared feed and cached timetable; combine updates for affected stops on the same trip and prioritise imminent departures. | Use predictions for the correct trip, stop and service date.  Keep the original source timestamp through every hop. |
| Radio schedule and time | Publish a versioned plan with group and coordinator IDs, revision, activation time, cycle length, slot assignments, repair and rendezvous windows.  Share trusted UTC and its quality when available.  Schedule enough receive time to hear member reports and traffic from other hops. | Cache the current and pending plans.  Forward only in assigned slots, account for clock drift and sleep between relevant windows.  Preserve source time, radio receipt time and passenger-clock confidence separately. |
| Change and recovery | Announce a replacement plan ahead of activation.  Keep the rendezvous window discoverable across revisions so sleeping members can recover a missed announcement.  Reassign a forwarding slot when a node reports low reserve or a link repeatedly fails. | Apply a complete plan at the stated boundary.  On coordinator loss use the cached plan while timing is good enough; when timing becomes uncertain use the rendezvous window to reacquire.  Expire live predictions on time and continue local timetable service. |

Start with one designated coordinator per group.  Peers can keep forwarding useful cached data while it is absent.  A standby coordinator is a later extension requiring a deterministic takeover rule and a test that two coordinators cannot issue competing schedules.  Keep group definitions, plan revisions and duty-change reasons visible in receiver logs so a field trace can explain which stops were served and when.

## Compatibility and upgrade order

Build and bench-test the gateway first.  Treat v0.8.4e at the Museum and its current PC gateway plus USB radio as the reference pair.  The following observations come from inspection of the v0.8.4e sign source and the [USB sender compatibility history](https://github.com/TheReverendCard/open-transit-display/issues/10#issuecomment-6226152705).  Mixed-version hardware tests are pending.

* Preserve the current serial bridge commands and responses, on-air radio settings, packet field counts, session and sequence handling, update cadence, and prompt replies to the sign's boot and stale-data requests.  The sign sends `OTDQ1`, accepts fixed-format `OTD2` and `OTD3` updates, and acknowledges them with `OTDA2`.  Its Wi-Fi-first build has LoRa timetable page recovery disabled.  Test clock sync, scheduled and live arrivals, ACKs and quiet-hours recovery on the existing sign.  Exercise timetable page repair later with a capable peer.
* Protect the Museum display on a shared channel.  Its `OTD2` parser accepts the stop and route carried in the packet without comparing them to the installed stop.  Limit this legacy traffic within earshot to the Museum stream.  Use a separately identified format with explicit destinations for other stops or separate their radio traffic.  Budget for radio wakes even when an old sign ignores a frame.  Keep legacy sequence numbering coherent so other stops' messages do not create false missing-packet counts.
* New signs start in the existing single-stop operating mode and can use today's gateway after a gateway rollback.  Enable a versioned mesh feature for a peer only after both sides confirm support.  A legacy ACK confirms receipt of a transit packet.  It carries no mesh capability negotiation.  Check USB bridge support for each new packet type wherever the PC path is used.  Earlier bridge firmware filtered outbound frames by prefix.
* Bench order: candidate gateway with unchanged Museum-version sign; candidate sign with current PC gateway and original radio bridge; both candidates with negotiated features; mixed group with one legacy sign.  Verify a gateway rollback as well as cold boot, overnight light sleep, first-service recovery, and isolation of other stops' arrivals.  Use a capable intermediate sign and an out-of-range destination to prove forwarding.  A gateway-only release can ship after its legacy-path checks; claims about mesh operation need the corresponding on-air tests.

## Receiver candidate v0.8.5, 14 November 2026

Owner package `OTD_Gateway_085.zip`, SHA-256 `0a703842a5d1823fed768aff33975179396d7d4c59960bab0cc54098ddd4ce83`.  This is the first receiver-side implementation of the preview.  The candidate includes the USB bridge sketch, Windows gateway, single-stop and corridor preview configurations, tests, Windows launcher and baseline bridge for rollback.  The field sign remains on v0.8.4e.

* The existing v0.8 receiver sketch now reports its capabilities and computes a plan locally for up to 12 configured stop/route pairs.  The Windows gateway distributed with v0.8.4b continues to acquire Museum data.  Over USB it supplies group membership, surveyed links, forwarding eligibility and a workload derived from overlapping departures in the dated GTFS.  The receiver picks minimum-hop parents, favours shared broadcasts within a hop layer and reports slot assignments, reserved time, delivery bound, unreachable members and budget result.  Preview configuration and results stay on USB.  Health and plan lines are timestamped in `gateway/coordinator_preview.log`.
* The on-air path keeps the Museum OTD2 stream, optional OTD3, legacy ACK format, HELLO/recovery handling and radio parameters.  The bridge checks the route and stop name on unaddressed OTD1/OTD2 arrivals.  The PC matches ACKs to the configured sign as well as the session and pending ID.  The updated PC queries the bridge once and submits a plan only to a preview-capable bridge.  An older Museum PC can continue to use the updated radio.
* Host checks passed: 10 candidate tests, 36 prior regression tests and a replay of 37 field uplinks through the sketch with simulated serial/radio.  The 14 November Museum feed produced one reserved 3-second slot per 60-second preview cycle; the illustrative two-frame corridor used two senders and reserved 12 seconds.  These are configured planning estimates.  Static feed reading and the PC entry point were exercised.  No ESP32 board compile, physical upload or RF test was performed in this build environment.
* Next field check: Arduino Verify and Upload on the USB receiver, then check `radio_ready=1`, a completed preview, a matched Museum ACK, correct passenger data, sleep recovery and the first service after a quiet night.  Over-air plan negotiation, autonomous Wi-Fi feed acquisition on the board, solar duty decisions and real forwarding remain pending.

## First v0.8.5 receiver field result, 14 November 2026

The owner's startup log at 15:27:53–15:27:58 NZDT shows the uploaded receiver running v0.8.5 with `preview=1 radio_ready=1 mesh_tx=0`.  The on-board Museum preview completed with `fits=1`, one sender, zero unreachable members, 3000 ms reserved per 60-second cycle and a configured 63000 ms delivery bound.  These are preview estimates.

The gateway transmitted N1 in session 382198413 with radio status 0.  Museum stop 11000262 returned a matching OTDA2 ACK in 1563 ms, reporting 3.992 V.  Its following OTDP1 diagnostic reported boot nonce 0B336F4A, uptime 100501 seconds (27 h 55 min 1 s), light sleep enabled and supported, 48010 sleep events, 95363 seconds asleep (94.9% of uptime), 427 GPIO wakes, 47583 timer wakes and zero reported sleep errors.  The sleep counters cover the sign's existing uptime, including operation before this gateway upload.  The ACK receive counter of 1 follows the new gateway session.  The receiver's `reset=11` is the receiver's own reset-reason report.  The sign supplied its continuing uptime and nonce in the separate power diagnostic.

This establishes successful installation, USB preview execution and initial radio exchange between the candidate gateway and the current sign.  Continued ACK reception, live arrival transition, physical screen correctness and quiet-period/first-service recovery remain field acceptance checks.  With the next scheduled departure at 16:15:07, the current 20-minute policy should start regular arrival updates around 15:55 NZDT, subject to live prediction and the running loop cadence.

## Windows installation layout, 14 November 2026

Use the owner's Documents/OTD as the permanent installation root for gateway and sign releases.  `Run_Gateway.ps1` and `run_gateway.py` provide the permanent Task Scheduler entry point.  `active-gateway.json` selects a version under `versions/gateway/<version>`.  Future sign packages belong under `versions/sign/<version>`.  Shared COM-port and group configuration lives under `shared/config`, feed caches under `shared/cache`, and histories and diagnostics under `shared/logs`.

The owner-local package `OTD_Documents_Setup.zip` (SHA-256 `0304f464b63800d0de3775e748d7b946d8bbcf1721e3993014ca0e9eec91fd3a`) installs gateway application 0.8.5.1.  It takes the current Downloads installation path supplied by the owner, copies it to a dated local backup, imports known logs and caches into shared storage on first install, and publishes the active selection after installation.  Repeat installations retain shared settings and data.  The bundled receiver source is byte-identical to v0.8.5.  The initial port is COM5 and the application uses the existing Museum stop/route and live-data arguments.

`shared/credentials` reserves a common location for protected provisioning credentials in future work.  The current public-feed PC gateway has no credential-file consumer, and device Wi-Fi provisioning is still on-device.  The installer copies private files already present in the old installation into its local backup.  Credential extraction, encrypted credential storage and automated device provisioning are pending.

Four migration tests and ten gateway compatibility tests passed, including shared data paths through the normal PC entry point.  Windows PowerShell/Task Scheduler and Windows file locking require an on-PC check.  The package has been prepared for the user; no Windows filesystem migration or scheduled-task change has been performed from this session.  Future releases should supply the shared-path options accepted by the permanent launcher and document any configuration migration.


## Task Scheduler follow-up, 14 November 2026

The owner reported that the Bus Sign Monitor task showed Running, enabled and allowed on demand, with a last-result value of `0xC0000602`.  Its action's Program field was `C:\Windows\System32\WindowsPowerShell\v1.0`, a directory.  Correct the action to `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`, retain the arguments pointing to `Documents\OTD\Run_Gateway.ps1`, and set the working directory to the installation root.  A later successful gateway ACK is still needed to verify the task launch.  The reported result is a fail-fast exception status and does not identify its originating process.

For an owner-visible console at sign-in, use the owner's interactive account, Run only when user is logged on, and an At log on trigger.  Background operation before sign-in uses a different task logon context.  Record the actual selected mode when the owner confirms the correction.  See [Microsoft logon modes](https://learn.microsoft.com/en-us/windows/win32/api/taskschd/ne-taskschd-task_logon_type) and [NTSTATUS values](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55).

## Background gateway console logging, 14 November 2026

The owner reports that the sign appears to receive live updates while the scheduler displays Running and Last Run Result `0xC0000602`, with no visible console.  Actual process ownership and the source of that exit status remain unverified.  Windows exposes current task state separately from the result returned by the last run.  Use fresh ACK records and process/output logs to verify current gateway activity.  [Microsoft task result](https://learn.microsoft.com/en-us/windows/win32/api/taskschd/nf-taskschd-iregisteredtask-get_lasttaskresult)

The updated `OTD_Documents_Setup.zip` adds `Install_Logging.cmd` for existing installations.  It installs an updated permanent launcher and an independent `View_Gateway_Log.cmd`, with dated backups of the prior launchers.  The supervisor captures both output streams from its child process into timestamped `shared/logs/gateway-console.log`, including process ID, active application path, errors, exit codes and retries.  The PowerShell entry point logs startup and pre-Python failures in `shared/logs/gateway-startup.log`.  A recorded Python executable path in `shared/config/python.json` supplies the interpreter for subsequent task launches.

The viewer tails the file and can be opened or closed independently of the gateway.  It introduces no additional serial-port consumer.  The update preserves the active application selection, firmware, settings and CSV history.  It takes effect on the next supervisor start.  The main console log appends across restarts.  Daily log rotation remains outside this patch.

Three new tests passed for child stdout/stderr capture, Unicode, retry after failure, headless logging, configuration errors and preservation during the patch.  Four migration tests also passed.  The Windows launcher and viewer need the owner's on-PC check.  Updated package SHA-256 is `89acae23b50163e33a91ca6dde87a5b825e6e087740d14689a157092b7953176`.


## Scheduled gateway failure and checked repair, 14 November 2026

At 16:23:16 NZDT the owner reported that `\\Bus Sign Monitor` was Ready.  Its last run at 16:21:57 returned `0xC0000602`, and both `shared/logs/gateway-startup.log` and `gateway-console.log` were absent.  This supersedes the earlier assumption that the task might still be running without a window.  Execution of the logging launcher is unconfirmed.  The original action had named the PowerShell directory without powershell.exe; whether that correction or the logging update reached the installed task is unknown.  The fail-fast result does not identify the failing process or establish the underlying cause.

The current `OTD_Documents_Setup.zip` adds `Repair_Gateway_Task.ps1` and supervisor revision `task-repair-1`.  It is a Windows startup repair, with no changes to the gateway application 0.8.5.1 payload, receiver firmware v0.8.5 or sign firmware v0.8.4e.  Extract the complete package and run the repair script in an existing PowerShell window.  The package README gives the commands.  The repair:

* Validates installed files and the recorded Python environment.  New `run_gateway.py --check` checks log writing, imports, timezone and group configuration without opening the serial port or feeds.  Missing dependencies and invalid local configuration fail before task-action replacement.
* Backs up the task XML, temporarily disables its triggers, stops a current instance and checks for another gateway process.  The logging patch saves prior launchers and retains the selected application, shared settings and historical CSV files.
* Changes only the action of the existing root `Bus Sign Monitor` task to the verified absolute python.exe path, with `-u "<OTD root>\\run_gateway.py"` and the OTD working directory.  Account, triggers and conditions remain.  It restores enabled status and requests one start.
* Reports the state and result after 15 seconds, and separately checks bytes appended since that start for a RUN-mode launcher marker.  A fresh launcher marker confirms startup only; fresh ACKs and continuing operation are required for field acceptance.  It does not claim to diagnose the original fail-fast cause.
* Writes repair progress to `shared/logs/gateway-task-repair.log` and gateway output to `gateway-console.log`.  Direct Python startup bypasses the PowerShell launcher, so a new `gateway-startup.log` is no longer expected.  `View_Gateway_Log.cmd` remains the independent live viewer.

If local validation fails, the task action is unchanged.  If the final task start fails, the checked Python action remains installed and the report says startup was not confirmed; the original action is in the dated XML backup.  A failure after temporary disable attempts to restore the enabled state.  Access-denied failures are reported for the owner to resolve with an elevated shell if necessary.  No dependencies are installed automatically and no other gateway process is killed.

All twelve local Python tests passed, including five new startup checks for success without gateway execution, missing live dependencies, invalid group configuration, invalid active-version paths and a bounded import timeout.  The seventeen packaged gateway payload files are byte-for-byte unchanged.  Native PowerShell 5.1 and Windows Task Scheduler are unavailable on the development host; the repair is delivered for the owner's on-PC run and the reported failure is **not yet confirmed resolved**.

Package SHA-256:  `0324d9b747ae8f73e1f64faa1670e40f2a4d81ac1cc75a3002368f589eb3b19d`.  The same Documents setup download now contains this repair.  Next evidence needed:  repair output, a fresh Museum ACK and sustained scheduled operation.

## Windows permission failure and repair v2, 14 November 2026

The owner ran repair v1 at 16:35 NZDT.  Logging launchers were installed with a dated backup, Python was pinned to the user's Python 3.12 executable, and the installed CHECK mode confirmed imports, timezone, group configuration and log writing on Windows.  These local startup checks are now field-confirmed; radio and network access were deliberately not exercised by CHECK.

`Set-ScheduledTask` and `Enable-ScheduledTask` returned Access is denied, HRESULT `0x80070005`.  The repair incorrectly continued after those errors and claimed that the direct Python action was installed.  That was a repair-script defect; the claim must not be treated as evidence of a saved task change.  At 16:35:37 the task was Ready, its most recent run had again returned `0xC0000602`, and no fresh scheduled launcher output was confirmed.  Permissions blocked the attempted repair; the original fail-fast cause is still unverified.

The same Documents setup ZIP now contains **Repair v2**.  Changes are limited to `Repair_Gateway_Task.ps1` and its README:

* Require an elevated PowerShell window for this one-time repair, using `#Requires -RunAsAdministrator`.  The existing task account and RunLevel are not changed.
* Add explicit `-ErrorAction Stop` to every scheduler operation and the process inventory read, so a rejected command enters failure handling.
* Read back the disabled/enabled state and saved Execute, Arguments and WorkingDirectory.  Report a saved Python action only after the values match.  Start only after action and enabled-state verification.
* Track whether the action was verified and report that accurately in failures.  Verify enabled-state restoration in cleanup and report any failure to restore it.

The owner's extracted path is `C:\\Users\\revje\\Documents\\OTD_Documents_Setup\\OTD_Documents_Setup`.  Replace that extracted package with the updated ZIP, open Windows PowerShell with Run as administrator, and invoke the repair with explicit `-Root "C:\\Users\\revje\\Documents\\OTD"`.  If permissions are still denied in the elevated shell, stop and inspect task access; do not assume an update succeeded.

Only the two named files changed relative to repair v1.  The Python supervisor, gateway payload and MCU firmware are unchanged.  Native execution of revised repair v2 is still pending on the owner's Windows PC.  The earlier twelve Python tests do not validate Windows scheduler permissions or PowerShell error handling.  The new package SHA-256 is `1ed6aa6acf499fe6935f5a4f843326127b186a1a1e72887cb60d61b877d47366`.

Next evidence:  saved-action verification from the elevated run, fresh scheduled RUN output and a new Museum ACK.  Microsoft documents [command-level ErrorAction](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_commonparameters?view=powershell-5.1) and [Task Scheduler access-denied troubleshooting](https://learn.microsoft.com/en-us/troubleshoot/windows-server/system-management-components/troubleshooting-task-scheduler-access-denied-error).

## Delivery sequence and evidence

1. **Receiver first.**  With the current PC gateway supplying data, add a capability report and a coordinator preview that logs group members, selected upstream stops, forwarders, radio windows and the reasons for each selection.  Replay an hourly Museum service and a busier overlapping service.  Verify that the plan covers every subscribed stop and stays within the chosen live-data freshness and radio airtime budgets.  The preview can be checked alongside the working sign before enabling mesh transmissions.
2. **First on-air milestone.**  Run the same candidate firmware on the headless receiver/gateway and the screen-equipped node.  Demonstrate timetable-only distribution with a missing-page repair, then a combined display and gateway.  Verify existing single-stop packets and ACK behaviour during migration.  Record reset reason, plan revision and timestamp quality on reboot.
3. **One corridor, one necessary forwarding hop.**  Place a third node beyond direct gateway reach.  Deliver a timetable revision and a live update in assigned slots.  Confirm expiry uses the original observation time.  Miss a plan announcement, remove upstream access and restart the coordinator.  Check rejoin, local fallback, independent first-service wake and far-stop delivery within the configured freshness budget.
4. **Solar field goal.**  Compare sign-only and sign-plus-forwarding operation under matched service loads, then exercise Wi-Fi gateway duty separately.  Log traffic volume, transmit airtime, radio/CPU awake time, far-stop update age, missed departures and daily pre-dawn reserve.  Record panel, site, charge recovery and weather over multiple day/night cycles.  Establish the traffic load that sustains forwarding without a continuing loss of reserve, including a busier service than the Museum baseline.  Publish the measured operating envelope and use it to choose default duty thresholds and slot lengths.
