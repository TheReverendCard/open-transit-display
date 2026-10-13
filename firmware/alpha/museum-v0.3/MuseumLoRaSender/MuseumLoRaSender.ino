/*
  USB-LoRa sender for Open Transit Display, XIAO ESP32S3 Plus + Wio-SX1262.
  One OTD1 packet per USB serial line from museum_gateway.py.
  RadioLib required; USB CDC On Boot enabled; 115200 baud; antenna attached.
*/
#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
static constexpr int RADIO_CS=41,RADIO_DIO1=39,RADIO_RST=42;
static constexpr int RADIO_BUSY=40,RADIO_RFSW=38;
SX1262 radio=new Module(RADIO_CS,RADIO_DIO1,RADIO_RST,RADIO_BUSY);
static bool ready=false;
static String lineBuffer;

void setup(){
  Serial.begin(115200);
  delay(1000);
  pinMode(RADIO_RFSW,OUTPUT);
  digitalWrite(RADIO_RFSW,LOW); // Wio RF switch: TX
  SPI.begin(7,8,9,RADIO_CS);
  int16_t s=radio.begin(915.0,125.0,9,7,0x12,10,8,1.8);
  if(s!=RADIOLIB_ERR_NONE){Serial.printf("ERR: init=%d\n",s);return;}
  radio.setDio2AsRfSwitch(true);
  ready=true;
  Serial.println("READY: Museum OTD1 serial-to-LoRa bridge");
}
void loop(){
  if(!ready){delay(100);return;}
  while(Serial.available()){
    char c=(char)Serial.read();
    if(c=='\r')continue;
    if(c=='\n'){
      String packet=lineBuffer;lineBuffer="";
      if(packet.length()==0)continue;
      if(!packet.startsWith("OTD1|")){Serial.println("ERR: expected OTD1 packet");continue;}
      if(packet.length()>220){Serial.println("ERR: packet too long");continue;}
      digitalWrite(RADIO_RFSW,LOW);
      int16_t status=radio.transmit(packet);
      Serial.printf("TX: bytes=%u status=%d\n",(unsigned)packet.length(),status);
    }else if(lineBuffer.length()<230)lineBuffer+=c;
  }
  delay(2);
}