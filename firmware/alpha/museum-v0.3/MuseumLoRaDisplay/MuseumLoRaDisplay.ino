/*
 Open Transit Display: Whangarei Museum, 800x480 EE04 / UC8179 prototype.
 Hardware: Seeed TRMNL DIY + XIAO ESP32S3 Plus + Wio-SX1262 B2B.
 Layout: firmware/layouts/site-default.json
 Fonts: temporary Seeed_GFX/TFT_eSPI fonts until Nimbus Sans output is available.
 Experimental prototype, not compiled or tested as Museum firmware.
 Required: RadioLib, Seeed_GFX, driver.h, MuseumTypes.h.
 XIAO_ESP32S3_PLUS, OPI PSRAM, USB CDC On Boot enabled.
*/
#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <TFT_eSPI.h>
#include <time.h>
#include <sys/time.h>
#include <math.h>
#include "esp_sleep.h"
#include "MuseumTypes.h"

static constexpr bool ENABLE_PARTIAL=true;
static constexpr bool ENABLE_OVERNIGHT_DEEP_SLEEP=false;
static constexpr int RADIO_CS=41,RADIO_DIO1=39,RADIO_RST=42;
static constexpr int RADIO_BUSY=40,RADIO_RFSW=38;
static constexpr uint32_t FULL_INTERVAL_MS=45UL*60*1000;
static constexpr int PARTIALS_PER_FULL=30;
static constexpr int WAKE_LEAD_SECONDS=20*60;

EPaper epaper;
SPIClass &sharedSPI=epaper.getSPIinstance();
SX1262 radio=new Module(RADIO_CS,RADIO_DIO1,RADIO_RST,RADIO_BUSY,
                      sharedSPI,SPISettings(2000000,MSBFIRST,SPI_MODE0));
volatile bool rxIrq=false;
void IRAM_ATTR radioInterrupt(){rxIrq=true;}
bool radioOK=false,displayReady=false,clockValid=false;
uint32_t partialCount=0,lastFullMs=0;
String lastClock="",lastETAText="";

RTC_DATA_ATTR uint32_t sleepMarker=0;
RTC_DATA_ATTR uint32_t epochBeforeSleep=0;
RTC_DATA_ATTR uint32_t scheduledSleepSec=0;
RTC_DATA_ATTR char rtcPacket[224]={0};

static constexpr Rect R_CLOCK={620,18,150,48};
static constexpr Rect R_STATUS={620,66,150,24};
static constexpr Rect R_UPDATED={620,92,150,16};
static constexpr Rect R_SCHED={6,274,229,92};
static constexpr Rect R_ETA={250,226,525,106};
static constexpr Rect R_MORE={255,333,520,64};
static constexpr Rect R_PREV={6,420,229,52};
static constexpr Rect R_NEXT={450,420,326,52};
static constexpr Rect R_CLOCK_GROUP={615,16,162,96};
static constexpr Rect R_MAIN_GROUP={246,223,532,180};
TransitData data;

void selectRadioReceive(){pinMode(RADIO_RFSW,OUTPUT);digitalWrite(RADIO_RFSW,HIGH);}
void prepareScreen(){digitalWrite(RADIO_CS,HIGH);}
void resumeRadio(){
  selectRadioReceive();
  if(!radioOK)return;
  int16_t e=radio.startReceive();
  if(e!=RADIOLIB_ERR_NONE)Serial.printf("RX restart ERROR %d\n",e);
}
String localHHMM(time_t epoch){
  if(epoch<=0)return "--:--";
  struct tm tmv={};localtime_r(&epoch,&tmv);
  char s[12];snprintf(s,sizeof(s),"%02d:%02d",tmv.tm_hour,tmv.tm_min);
  return String(s);
}
bool sameLocalDate(time_t a,time_t b){
  if(a==0||b==0)return false;
  struct tm aa={};struct tm bb={};localtime_r(&a,&aa);localtime_r(&b,&bb);
  return aa.tm_year==bb.tm_year&&aa.tm_yday==bb.tm_yday;
}
// Approximate geometric sunrise/sunset in Whangarei. For power/display only.
bool isDark(time_t epoch){
  if(epoch<=0)return false;
  struct tm tmv={};localtime_r(&epoch,&tmv);
  constexpr double lat=-35.725*M_PI/180.0;
  constexpr double lon=174.310;
  double gamma=(2.0*M_PI/365.0)*(tmv.tm_yday+0.5);
  double eq=229.18*(0.000075+0.001868*cos(gamma)-0.032077*sin(gamma)-
                    0.014615*cos(2*gamma)-0.040849*sin(2*gamma));
  double dec=0.006918-0.399912*cos(gamma)+0.070257*sin(gamma)-
             0.006758*cos(2*gamma)+0.000907*sin(2*gamma)-
             0.002697*cos(3*gamma)+0.00148*sin(3*gamma);
  double h=acos(constrain(cos(90.833*M_PI/180.0)/(cos(lat)*cos(dec))-tan(lat)*tan(dec),-1.,1.));
  // The configured NZST-12NZDT zone is +12h standard and +13h DST.
  // tm_gmtoff is unavailable in some ESP32/newlib builds.
  int offsetMin=720+(tmv.tm_isdst>0?60:0);
  double noon=720-4*lon-eq+offsetMin;
  double sunrise=noon-h*180/M_PI*4;
  double sunset=noon+h*180/M_PI*4;
  int minute=tmv.tm_hour*60+tmv.tm_min;
  return minute<(int)sunrise||minute>=(int)sunset;
}
String displayClock(time_t now){
  if(!clockValid||now<1600000000)return "--:--";
  if(!isDark(now))return localHHMM(now);
  struct tm t={};localtime_r(&now,&t);
  t.tm_min=(t.tm_min/5)*5;
  char s[14];snprintf(s,sizeof(s),"~%02d:%02d",t.tm_hour,t.tm_min);
  return String(s);
}
// Temporary built-in fonts until the separately-owned Nimbus Sans generator
// produces licensed firmware assets. Region positions track site-default.json.
void textRegion(const Rect &r,const String &str,int align=0,int maxScale=3){
  if(str.length()==0)return;
  const uint8_t candidates[]={4,2,1};
  uint8_t font=1;int scale=1;bool chosen=false;
  for(uint8_t f:candidates){
    for(int s=maxScale;s>=1;s--){
      epaper.setTextSize(s);
      if(epaper.textWidth(str,f)<=r.w-4&&epaper.fontHeight(f)<=r.h-2){
        font=f;scale=s;chosen=true;break;
      }
    }
    if(chosen)break;
  }
  epaper.setTextSize(scale);
  epaper.setTextColor(TFT_BLACK,TFT_WHITE);
  epaper.setTextDatum(align==1?ML_DATUM:(align==2?MR_DATUM:MC_DATUM));
  int x=align==1?r.x+2:(align==2?r.x+r.w-2:r.x+r.w/2);
  epaper.drawString(str,x,r.y+r.h/2,font);
  epaper.setTextSize(1);
}
void clearRegion(const Rect &r){epaper.fillRect(r.x,r.y,r.w,r.h,TFT_WHITE);}
void redrawClock(time_t now){
  clearRegion(R_CLOCK_GROUP);
  textRegion(R_CLOCK,displayClock(now),2,2);
  if(data.valid&&data.source!="SCHED")textRegion(R_STATUS,data.source,2,1);
  if(data.valid&&data.source!="SCHED"&&data.generated>0){
    long age=(long)(now-data.generated)/60;
    textRegion(R_UPDATED,"UPDATED "+String(max(0L,age))+"m AGO",2,1);
  }
}
String remainingText(time_t now){
  if(!data.valid)return "AWAITING DATA";
  time_t t=(data.source=="SCHED"||!data.predicted)?data.scheduled:data.predicted;
  if(t<=0)return "NO SERVICES";
  if(!sameLocalDate(t,now))return "NEXT SERVICE";
  long mins=(t-now+59)/60;
  if(mins<=0)return "DUE";
  if(mins<=20)return "In "+String(mins)+" min";
  return localHHMM(t);
}
void redrawMain(time_t now){
  clearRegion(R_MAIN_GROUP);
  textRegion(R_ETA,remainingText(now),0,3);
  if(data.source=="SCHED")textRegion(R_MORE,"TIMETABLE ONLY",0,2);
  else if(data.predicted){
    textRegion({330,333,175,64},localHHMM(data.predicted),0,2);
    textRegion({525,333,240,64},"LIVE ETA",1,1);
  }
}
void redrawScheduled(){
  clearRegion(R_SCHED);clearRegion(R_PREV);clearRegion(R_NEXT);
  textRegion({6,274,229,22},"SCHEDULED",0,1);
  textRegion({6,304,229,62},localHHMM(data.scheduled),0,2);
  textRegion({6,420,229,16},"PREVIOUS",0,1);
  textRegion({6,439,229,32},localHHMM(data.previous),0,1);
  textRegion({450,420,326,16},"FOLLOWING",2,1);
  textRegion({450,439,326,32},localHHMM(data.following),2,1);
}
void drawAll(time_t now){
  prepareScreen();
  epaper.fillScreen(TFT_WHITE);
  epaper.drawRect(1,1,798,478,TFT_BLACK);
  epaper.drawRect(3,3,794,474,TFT_BLACK);
  epaper.drawRoundRect(10,10,221,206,28,TFT_BLACK);
  epaper.drawRoundRect(14,14,213,198,24,TFT_BLACK);
  epaper.drawLine(235,6,235,414,TFT_BLACK);
  epaper.drawLine(235,120,794,120,TFT_BLACK);
  epaper.drawLine(235,121,794,121,TFT_BLACK);
  epaper.drawLine(235,220,794,220,TFT_BLACK);
  epaper.drawLine(6,414,794,414,TFT_BLACK);
  epaper.drawLine(6,415,794,415,TFT_BLACK);
  epaper.drawLine(241,414,241,474,TFT_BLACK);
  textRegion({24,14,193,198},data.route,0,4);
  textRegion({255,20,355,88},data.direction,1,2);
  textRegion({255,128,520,42},data.stop,1,1);
  textRegion({255,174,520,40},"Next departure",1,1);
  redrawClock(now);redrawMain(now);redrawScheduled();
}
void screenRefresh(bool full,const Rect &r){
  if(!displayReady)return;
  prepareScreen();
  if(!full&&!ENABLE_PARTIAL)full=true;
  if(!full&&(partialCount>=PARTIALS_PER_FULL||
    millis()-lastFullMs>=FULL_INTERVAL_MS))full=true;
  uint32_t start=millis();
  if(full){epaper.update();partialCount=0;lastFullMs=millis();}
  else{epaper.updataPartial(r.x,r.y,r.w,r.h);partialCount++;}
  selectRadioReceive();
  Serial.printf("EPD %s duration=%lu ms partials=%lu\n",
     full?"FULL":"PARTIAL",(unsigned long)(millis()-start),
     (unsigned long)partialCount);
}
void refreshAfterData(const TransitData &before){
  time_t now=time(nullptr);
  bool major=!before.valid||before.route!=data.route||
     before.direction!=data.direction||before.stop!=data.stop;
  bool schedules=!before.valid||before.scheduled!=data.scheduled||
     before.previous!=data.previous||before.following!=data.following;
  bool other=!before.valid||before.predicted!=data.predicted||
     before.source!=data.source||
     (data.source!="SCHED"&&before.generated!=data.generated)||
     before.scheduled!=data.scheduled;
  String clockNow=displayClock(now),etaNow=remainingText(now);
  bool clockChange=clockNow!=lastClock,etaChange=etaNow!=lastETAText;
  if(major||schedules||!ENABLE_PARTIAL){
    drawAll(now);screenRefresh(true,{0,0,800,480});
  }else if(other||clockChange||etaChange){
    bool needClock=clockChange||(other&&data.source!="SCHED");
    bool needMain=other||etaChange;
    if(needClock)redrawClock(now);
    if(needMain)redrawMain(now);
    Rect update=needClock&&needMain?Rect{246,16,532,387}:
       (needClock?R_CLOCK_GROUP:R_MAIN_GROUP);
    screenRefresh(false,update);
  }
  lastClock=clockNow;lastETAText=etaNow;
}
bool parsePacket(const String &p,TransitData &parsed){
  // OTD1|unix|route|direction|stop|scheduled|predicted|source|previous|following|nextService
  if(!p.startsWith("OTD1|"))return false;
  String f[11];int count=0,begin=0;
  for(int i=0;i<=p.length();i++){
    if(i==(int)p.length()||p[i]=='|'){
      if(count>=11)return false;
      f[count++]=p.substring(begin,i);begin=i+1;
    }
  }
  if(count!=11||f[0]!="OTD1"||f[7].isEmpty())return false;
  time_t epoch=(time_t)strtoll(f[1].c_str(),nullptr,10);
  if(epoch<1600000000||epoch>2200000000)return false;
  parsed.route=f[2];parsed.direction=f[3];parsed.stop=f[4];
  parsed.scheduled=(time_t)strtoll(f[5].c_str(),nullptr,10);
  parsed.predicted=(time_t)strtoll(f[6].c_str(),nullptr,10);
  parsed.source=f[7];
  parsed.previous=(time_t)strtoll(f[8].c_str(),nullptr,10);
  parsed.following=(time_t)strtoll(f[9].c_str(),nullptr,10);
  parsed.nextService=(time_t)strtoll(f[10].c_str(),nullptr,10);
  parsed.generated=epoch;parsed.valid=true;
  if(parsed.source!="SCHED"&&parsed.source!="LIVE"&&
     parsed.source!="CACHED"&&parsed.source!="EST")return false;
  if(parsed.route.length()>10||parsed.stop.length()>60||
     parsed.direction.length()>50)return false;
  struct timeval tv={};tv.tv_sec=epoch;settimeofday(&tv,nullptr);
  clockValid=true;
  return true;
}
void maybeOvernightSleep(){
  if(!ENABLE_OVERNIGHT_DEEP_SLEEP||!clockValid||!data.valid)return;
  time_t now=time(nullptr);
  if(data.nextService<=now+WAKE_LEAD_SECONDS)return;
  if(sameLocalDate(data.nextService,now))return;
  int64_t s=(int64_t)data.nextService-(int64_t)now-WAKE_LEAD_SECONDS;
  if(s<=60||s>48*3600)return;
  Serial.printf("Overnight sleep %lld sec to 20min before next service\n",(long long)s);
  epochBeforeSleep=(uint32_t)now;
  scheduledSleepSec=(uint32_t)s;
  sleepMarker=0x0D71051;
  esp_sleep_enable_timer_wakeup((uint64_t)s*1000000ULL);
  Serial.flush();esp_deep_sleep_start();
}
void setup(){
  Serial.begin(115200);delay(500);
  setenv("TZ","NZST-12NZDT,M9.5.0/2,M4.1.0/3",1);tzset();
  Serial.println("Museum Open Transit Display booting");
  if(sleepMarker==0x0D71051&&esp_sleep_get_wakeup_cause()==ESP_SLEEP_WAKEUP_TIMER){
    if(rtcPacket[0]){
      TransitData restore;
      if(parsePacket(String(rtcPacket),restore))data=restore;
    }
    struct timeval tv={};
    tv.tv_sec=(time_t)(epochBeforeSleep+scheduledSleepSec);
    settimeofday(&tv,nullptr);clockValid=true;
    Serial.println("Woke from timed sleep; showing cached schedule; awaiting LoRa");
  }
  pinMode(RADIO_CS,OUTPUT);digitalWrite(RADIO_CS,HIGH);
  epaper.begin();epaper.setRotation(0);
  displayReady=true;
  drawAll(time(nullptr));screenRefresh(true,{0,0,800,480});
  sharedSPI.end();sharedSPI.begin(7,8,9,-1);
  Serial.println("Shared SPI initialised 7/8/9");
  selectRadioReceive();
  int16_t e=radio.begin(915.0,125.0,9,7,0x12,10,8,1.8);
  if(e!=RADIOLIB_ERR_NONE){Serial.printf("Radio init ERROR %d\n",e);return;}
  radio.setDio2AsRfSwitch(true);
  radio.setPacketReceivedAction(radioInterrupt);
  radioOK=true;resumeRadio();
  lastClock=displayClock(time(nullptr));
  lastETAText=remainingText(time(nullptr));
}
void loop(){
  if(!radioOK){delay(200);return;}
  if(rxIrq){
    rxIrq=false;
    String packet;
    int16_t e=radio.readData(packet);
    if(e==RADIOLIB_ERR_NONE){
      TransitData candidate;
      if(parsePacket(packet,candidate)){
        Serial.printf("OTD packet RSSI=%.1f SNR=%.1f: %s\n",radio.getRSSI(),radio.getSNR(),packet.c_str());
        TransitData old=data;data=candidate;
        packet.toCharArray(rtcPacket,sizeof(rtcPacket));
        refreshAfterData(old);
        maybeOvernightSleep();
      }else Serial.println("Ignored invalid OTD1 payload");
    }else Serial.printf("LoRa reception error %d\n",e);
    resumeRadio();
  }
  time_t now=time(nullptr);
  String clockNow=displayClock(now),etaNow=remainingText(now);
  bool changedClock=clockValid&&clockNow!=lastClock;
  bool changedETA=clockValid&&etaNow!=lastETAText;
  if(changedClock||changedETA){
    int16_t e=radio.standby();
    if(e==RADIOLIB_ERR_NONE){
      if(changedClock)redrawClock(now);
      if(changedETA)redrawMain(now);
      Rect r=changedClock&&changedETA?Rect{246,16,532,387}:
        (changedClock?R_CLOCK_GROUP:R_MAIN_GROUP);
      screenRefresh(false,r);
      resumeRadio();lastClock=clockNow;lastETAText=etaNow;
    }
  }
  delay(40);
}