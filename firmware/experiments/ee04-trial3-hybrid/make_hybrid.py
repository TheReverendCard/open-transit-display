from pathlib import Path
import shutil
import sys

source, output = (Path(p).resolve() for p in sys.argv[1:3])
if output.exists() or output == source or source in output.parents:
    raise SystemExit("Choose a fresh output folder outside trial3.")
text = (source / "OTDUnified_v086.ino").read_text(encoding="utf-8-sig")
start = text.index("void screenRefresh(bool forceFull,bool clockArea,bool mainArea){")
end = text.index("\n}\n", start) + 3
assert text.count("screenRefresh(true,true,true);") == 2
assert text.count('#include "OTDDisplayStorage.h"') == 1
text = text[:start] + '''void screenRefresh(bool forceFull,bool clockArea,bool mainArea){
  if(!displayReady)return;
  prepareScreen();
#if OTD_ENABLE_DIFFERENTIAL
  static OTDDifferentialRefresh hybrid;
  static bool fullOnly=false;
  if(!fullOnly){
    // Before radio setup the Seeed bus can be transmit-only. Keep its
    // proven startup draw; the first scheduled slot establishes the Gx baseline.
    if(!forceFull && hybrid.update(epaper, sharedSPI, false)){
      selectRadioReceive();
      return;
    }
    if(!forceFull){
      fullOnly=true;
      Serial.println("EPD differential fault; Seeed full refresh until reboot");
      epaper.begin();
      epaper.setRotation(0);
      sharedSPI.end();
      sharedSPI.begin(7,8,9,-1);
    }
  }
#endif
  epaper.update();
  ++fullRefreshEvents;
  lastFullMs=millis();
  selectRadioReceive();
  Serial.println("EPD FULL driver=Seeed");
}
''' + text[end:]
prefix, marker, tail = text.rpartition("screenRefresh(true,true,true);")
assert marker
text = prefix + "screenRefresh(false,true,true);" + tail
text = text.replace('#include "OTDDisplayStorage.h"', '''#include "OTDDisplayStorage.h"
#ifndef OTD_ENABLE_DIFFERENTIAL
#define OTD_ENABLE_DIFFERENTIAL 1
#endif
#if OTD_ENABLE_DIFFERENTIAL
#include "OTDDifferentialRefresh.h"
#endif''')
output.mkdir(parents=True)
for p in source.iterdir():
    if p.name in ("src", "licenses"):
        shutil.copytree(p, output / p.name)
    elif p.suffix == ".h":
        shutil.copy2(p, output / p.name)
shutil.copy2(Path(__file__).with_name("OTDDifferentialRefresh.h"), output)
(output / (output.name + ".ino")).write_text(text, encoding="utf-8")
print(output)
