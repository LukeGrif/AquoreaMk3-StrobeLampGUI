#include <SPI.h>
#include <UIPEthernet.h>
#include <SoftwareSerial.h>

// ---------- RS-485 pins ----------
#define DE 3
#define RE 4
#define RS485_RX 8  // RO
#define RS485_TX 9  // DI
SoftwareSerial RS485Serial(RS485_RX, RS485_TX);  // RX, TX

// ---------- Ethernet (ENC28J60) ----------
const uint8_t ENC28J60_CS = 10;  // D10 = CS (SPI uses D11/D12/D13)
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED };
IPAddress ip(192, 168, 3, 70);
IPAddress dnsServer(192, 168, 2, 1);
IPAddress gateway(192, 168, 2, 1);
IPAddress subnet(255, 255, 255, 0);

const uint16_t PORT = 9000;
EthernetServer server(PORT);

// ---------- State ----------
uint8_t strobeIntensity = 0;
uint8_t lampIntensity   = 0;
bool lampOn = false;

// ---------- Exposure Counter ----------
const int exposurePin = 7;
volatile unsigned long exposureCount = 0;
volatile bool exposureCounting = false; // controlled from GUI

void exposureISR() {
  if (exposureCounting) {
    exposureCount++;
  }
}

void resetExposureCount() {
  noInterrupts();
  exposureCount = 0;
  interrupts();
}

unsigned long getExposureCount() {
  noInterrupts();
  unsigned long val = exposureCount;
  interrupts();
  return val;
}

// ---------- Forward decl ----------
void rs485_send_line(const String &s);
void rs485_poll(EthernetClient *client);

// ---------- TCP helpers ----------
void sendLine(EthernetClient &c, const char *s) {
  c.write((const uint8_t *)s, strlen(s));
  c.write('\n');
}

bool maybe_forward_rs485(const String &cmd, EthernetClient &client) {
  if (cmd.length() && (cmd.charAt(0) == '~' || cmd.charAt(0) == '$')) {
    rs485_send_line(cmd);
    Serial.print(F("[FWD RS485] ")); Serial.println(cmd);
    sendLine(client, "OK FORWARDED");
    return true;
  }
  return false;
}

// ===== RS-485 MONITOR =====
void rs485_poll(EthernetClient *client) {
  static char buf[160];
  static uint8_t idx = 0;
  static uint32_t lastByteMs = 0;
  const uint16_t idleFlushMs = 30;

  while (RS485Serial.available()) {
    int b = RS485Serial.read();
    if (b < 0) break;
    lastByteMs = millis();

    char ch = (char)b;

    if (ch == '\r' || ch == '\n') {
      if (idx > 0) {
        buf[idx] = '\0';
        Serial.print(F("[RS485<-] ")); Serial.println(buf);
        if (client && client->connected()) {
          String out = String("RS485: ") + buf;
          sendLine(*client, out.c_str());
        }
        idx = 0;
      }
      continue;
    }

    if (idx < sizeof(buf) - 1) {
      buf[idx++] = ch;
    } else {
      buf[idx] = '\0';
      Serial.print(F("[RS485<-] ")); Serial.println(buf);
      if (client && client->connected()) {
        String out = String("RS485: ") + buf;
        sendLine(*client, out.c_str());
      }
      idx = 0;
    }
  }

  if (idx > 0 && (millis() - lastByteMs) > idleFlushMs) {
    buf[idx] = '\0';
    Serial.print(F("[RS485<-] ")); Serial.println(buf);
    if (client && client->connected()) {
      String out = String("RS485: ") + buf;
      sendLine(*client, out.c_str());
    }
    idx = 0;
  }
}

void handleCommand(const String &line, EthernetClient &client) {
  String cmd = line;
  cmd.trim();
  if (cmd.length() == 0) return;

  if (maybe_forward_rs485(cmd, client)) return;

  // ---------- Exposure commands ----------
  if (cmd.equalsIgnoreCase("START_EXPOSURE_COUNT")) {
    resetExposureCount();
    exposureCounting = true;
    sendLine(client, "OK EXPOSURE COUNT STARTED");
    return;
  }

  if (cmd.equalsIgnoreCase("STOP_EXPOSURE_COUNT")) {
    exposureCounting = false;
    sendLine(client, "OK EXPOSURE COUNT STOPPED");
    return;
  }

  if (cmd.equalsIgnoreCase("GET_EXPOSURE_COUNT")) {
    unsigned long val = getExposureCount();
    char buf[40];
    sprintf(buf, "EXPOSURE_COUNT %lu", val);
    sendLine(client, buf);
    return;
  }

  // ---------- Existing commands ----------
  if (cmd.equalsIgnoreCase("LAMP OFF")) {
    String data = "~device set lamp:000|SUBC24991";
    rs485_send_line(data);
    lampOn = false;
    sendLine(client, "OK LAMP OFF");
    return;
  }

  if (cmd.startsWith("STROBE_INTENSITY")) {
    int sep = cmd.indexOf(' ');
    if (sep > 0) {
      int v = cmd.substring(sep + 1).toInt();
      if (v >= 0 && v <= 100) {
        strobeIntensity = (uint8_t)v;
        char buf[50];
        sprintf(buf, "~device set strobe:%03d|SUBC24991", strobeIntensity);
        rs485_send_line(buf);
        sendLine(client, "OK STROBE_INTENSITY");
      } else {
        sendLine(client, "ERR STROBE_INTENSITY OUT OF RANGE");
      }
    }
    return;
  }

  if (cmd.startsWith("LAMP_INTENSITY")) {
    int sep = cmd.indexOf(' ');
    if (sep > 0) {
      int v = cmd.substring(sep + 1).toInt();
      if (v >= 0 && v <= 100) {
        lampIntensity = (uint8_t)v;
        char buf[50];
        sprintf(buf, "~device set lamp:%03d|SUBC24991", lampIntensity);
        rs485_send_line(buf);
        sendLine(client, "OK LAMP_INTENSITY");
      } else {
        sendLine(client, "ERR LAMP_INTENSITY OUT OF RANGE");
      }
    }
    return;
  }

  if (cmd.equalsIgnoreCase("STATUS")) {
    String data = "~comms print status|SUBC24991";
    rs485_send_line(data);
    sendLine(client, "OK STATUS");
    return;
  }

  sendLine(client, "UNKNOWN CMD");
}

// ---------- RS-485 helpers ----------
void rs485_send_line(const String &s) {
  digitalWrite(RE, HIGH);
  digitalWrite(DE, HIGH);
  delayMicroseconds(5);
  RS485Serial.print(s);
  RS485Serial.print("\r\n");
  RS485Serial.flush();
  delayMicroseconds(5);
  digitalWrite(DE, LOW);
  digitalWrite(RE, LOW);
}

void setup() {
  Serial.begin(9600);

  // RS-485
  RS485Serial.begin(9600);
  pinMode(DE, OUTPUT);
  pinMode(RE, OUTPUT);
  digitalWrite(DE, LOW);
  digitalWrite(RE, LOW);

  // Ethernet
  pinMode(ENC28J60_CS, OUTPUT);
  digitalWrite(ENC28J60_CS, HIGH);
  Ethernet.init(ENC28J60_CS);
  Ethernet.begin(mac, ip, dnsServer, gateway, subnet);
  server.begin();

  // Exposure counter
  pinMode(exposurePin, INPUT);
  attachInterrupt(digitalPinToInterrupt(exposurePin), exposureISR, RISING);

  Serial.print(F("IP: ")); Serial.println(Ethernet.localIP());
}

void loop() {
  rs485_poll(nullptr);

  EthernetClient client = server.available();
  if (!client) return;

  String line = "";
  while (client.connected()) {
    while (client.available()) {
      char ch = client.read();
      if (ch == '\n') {
        handleCommand(line, client);
        line = "";
      } else if (ch != '\r') {
        if (line.length() < 120) line += ch;
      }
    }
    rs485_poll(&client);
  }

  client.stop();
}
