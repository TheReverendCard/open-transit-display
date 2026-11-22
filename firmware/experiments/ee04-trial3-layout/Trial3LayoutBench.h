// SPDX-License-Identifier: GPL-3.0-or-later
#include <GxEPD2.h>
#include <gdey/GxEPD2_750_GDEY075T7.h>

static GxEPD2_750_GDEY075T7 benchPanel(44, 10, 38, 4);
static uint8_t benchPrevious[48000], benchCurrent[48000];
static constexpr time_t benchStart = 1795374480; // Fixed, simulated epoch.
static unsigned benchStep, benchCleanEvery=5;
static bool benchAuto=true, benchFault=false, benchSawBusy=false, benchTx=false;
static uint32_t benchDue;

static void benchBusy(const void*) { benchSawBusy=true; delay(1); }

static uint8_t benchReverse(uint8_t b) {
  b=(b>>4)|(b<<4);
  b=((b&0xcc)>>2)|((b&0x33)<<2);
  return ((b&0xaa)>>1)|((b&0x55)<<1);
}

static void benchSnapshot() {
  const auto* pixels=static_cast<const uint8_t*>(epaper.getPointer());
#ifdef EPD_HORIZONTAL_MIRROR
  for(int y=0;y<480;++y)
    for(int x=0;x<100;++x)
      benchCurrent[y*100+x]=benchReverse(pixels[y*100+99-x]);
#else
  memcpy(benchCurrent,pixels,sizeof benchCurrent);
#endif
}

static bool benchTransmit() {
  if(!radioOK){
    int16_t rc=radio.beginOtdRadio();
    if(rc==RADIOLIB_ERR_NONE)rc=radio.setDio2AsRfSwitch(true);
    if(rc!=RADIOLIB_ERR_NONE){Serial.printf("Wio init error=%d\n",rc);return false;}
    radioOK=true;
  }
  if(radio.standby()!=RADIOLIB_ERR_NONE)return false;
  selectRadioTransmit();delay(10);
  const int16_t rc=radio.transmit(String("OTDXP1|LAYOUT|")+benchStep);
  selectRadioReceive();delay(10);
  Serial.printf("TX status=%d\n",rc);
  return rc==RADIOLIB_ERR_NONE;
}

static void benchDraw() {
  if(benchFault)return;
  const bool full=benchStep==0 || (benchCleanEvery && benchStep%benchCleanEvery==0);
  const bool tx=benchTx && benchStep>0;
  if(tx){
    if(!benchTransmit()){benchAuto=false;Serial.println("Stopped after TX failure. Restart with diff, hybrid or full.");return;}
    benchPanel.init(0,false,10,false);
  }
  const time_t now=benchStart+benchStep*60;
  const time_t firstDeparture=benchStart+4*60;
  data.scheduled=data.predicted=now<firstDeparture?firstDeparture:firstDeparture+20*60;
  data.previous=data.scheduled-20*60;
  data.following=data.scheduled+20*60;
  data.generated=now;
  drawAll(now);
  benchSnapshot();
  const uint32_t start=millis();
  benchPanel.writeImageToPrevious(benchStep?benchPrevious:benchCurrent,0,0,800,480);
  benchPanel.writeImage(benchCurrent,0,0,800,480);
  const uint32_t drive=millis();
  benchSawBusy=false;
  benchPanel.refresh(!full);
  const uint32_t duration=millis()-drive;
  const bool ok=benchSawBusy && digitalRead(4)==HIGH && duration<10000;
  benchPanel.powerOff();
  Serial.printf("LAYOUT step=%u clock=%s waveform=%s tx_before=%d drive_ms=%lu total_ms=%lu result=%s\n",
    benchStep,localHHMM(now).c_str(),full?"full":"differential",tx,
    (unsigned long)duration,(unsigned long)(millis()-start),ok?"ready":"fault");
  if(ok)memcpy(benchPrevious,benchCurrent,sizeof benchPrevious);
  else {benchFault=true;benchAuto=false;}
  if(benchStep>=15)benchAuto=false;
  benchDue=millis()+60000;
}

static void benchCommand(const char* cmd) {
  if(!strcmp(cmd,"next")){
    if(benchStep<15){++benchStep;benchDraw();}
  }else if(!strcmp(cmd,"stop"))benchAuto=false;
  else if(!strcmp(cmd,"hybrid")||!strcmp(cmd,"diff")||!strcmp(cmd,"full")||!strcmp(cmd,"radio")){
    benchCleanEvery=!strcmp(cmd,"diff")?0:!strcmp(cmd,"full")?1:5;
    benchTx=!strcmp(cmd,"radio");
    benchStep=0;
    benchAuto=!benchFault;
    benchDraw();
  }else Serial.println("Commands: next, hybrid, diff, full, radio, stop");
}

void setup(){
  Serial.begin(115200);
  delay(600);
  setenv("TZ","NZST-12NZDT,M9.5.0/2,M4.1.0/3",1);tzset();
  pinMode(RADIO_CS,OUTPUT);digitalWrite(RADIO_CS,HIGH);
  nodePanel=&otdDisplayPanel();
  if(!epaper.getPointer()||epaper.width()!=800||epaper.height()!=480||epaper.getColorDepth()!=1){
    benchFault=true;benchAuto=false;Serial.println("Invalid trial3 display buffer");return;
  }
  epaper.begin();epaper.setRotation(0);displayReady=true;
  sharedSPI.end();sharedSPI.begin(7,8,9,-1);
  benchPanel.selectSPI(sharedSPI,SPISettings(4000000,MSBFIRST,SPI_MODE0));
  benchPanel.init(0,true,10,false);
  benchPanel.setBusyCallback(benchBusy);
  clockValid=true;
  data.valid=true;
  data.source="LIVE";
  batteryPercent=83;
  batteryVolts=3.97f;
  Serial.println("SIMULATED timetable and battery. Bench only. Type help or next. Attach antenna before radio.");
  benchDraw();
}

void loop(){
  static char line[20];
  static size_t len;
  while(Serial.available()){
    const int c=Serial.read();
    if(c=='\n'||c=='\r'){
      if(len){line[len]=0;benchCommand(line);len=0;}
    }else if(len<sizeof(line)-1&&c>=32&&c<=126)line[len++]=char(c);
  }
  if(benchAuto && (int32_t)(millis()-benchDue)>=0){++benchStep;benchDraw();}
  delay(2);
}
