#include <SPI.h>
#include <UIPEthernet.h>

// --- Network (ENC28J60) ---
const uint8_t ENC28J60_CS = 10;  // Nano shields typically D10

byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED };
IPAddress ip(192, 168, 2, 70);
IPAddress dnsServer(192, 168, 2, 1);
IPAddress gateway(192, 168, 2, 1);
IPAddress subnet(255, 255, 255, 0);

// Raw TCP server (no HTTP)
const uint16_t PORT = 9000;
EthernetServer server(PORT);

// (optional) keep your pin around if you’ll use it later
const int outputPin = 3;

// --- State ---
uint8_t strobeIntensity = 0;  // 0..100
uint8_t lampIntensity = 0;    // 0..100
bool lampOn = false;

// --- TCP helpers ---
void sendLine(EthernetClient &c, const char *s) {
  c.write((const uint8_t *)s, strlen(s));
  c.write('\n');
}

void handleCommand(const String &line, EthernetClient &client) {
  String cmd = line;
  cmd.trim();
  if (cmd.length() == 0) return;

  // LAMP ON/OFF
  if (cmd.equalsIgnoreCase("LAMP ON")) {
    lampOn = true;
    Serial.println(F("[CMD] LAMP ON (simulated)"));
    sendLine(client, "OK LAMP ON");
    return;
  }
  if (cmd.equalsIgnoreCase("LAMP OFF")) {
    lampOn = false;
    Serial.println(F("[CMD] LAMP OFF (simulated)"));
    sendLine(client, "OK LAMP OFF");
    return;
  }

  // STROBE_INTENSITY <0..100>
  if (cmd.startsWith("STROBE_INTENSITY")) {
    int sep = cmd.indexOf(' ');
    if (sep > 0) {
      int v = cmd.substring(sep + 1).toInt();
      if (v >= 0 && v <= 100) {
        strobeIntensity = (uint8_t)v;
        Serial.print(F("[CMD] STROBE_INTENSITY -> "));
        Serial.println(strobeIntensity);
        sendLine(client, "OK STROBE_INTENSITY");
      } else {
        sendLine(client, "ERR STROBE_INTENSITY OUT OF RANGE (0-100)");
      }
    } else {
      sendLine(client, "ERR STROBE_INTENSITY NEEDS VALUE");
    }
    return;
  }

  // LAMP_INTENSITY <0..100>
  if (cmd.startsWith("LAMP_INTENSITY")) {
    int sep = cmd.indexOf(' ');
    if (sep > 0) {
      int v = cmd.substring(sep + 1).toInt();
      if (v >= 0 && v <= 100) {
        lampIntensity = (uint8_t)v;
        Serial.print(F("[CMD] LAMP_INTENSITY -> "));
        Serial.println(lampIntensity);
        sendLine(client, "OK LAMP_INTENSITY");
      } else {
        sendLine(client, "ERR LAMP_INTENSITY OUT OF RANGE (0-100)");
      }
    } else {
      sendLine(client, "ERR LAMP_INTENSITY NEEDS VALUE");
    }
    return;
  }

  // STATUS -> report current state
  if (cmd.equalsIgnoreCase("STATUS")) {
    Serial.println(F("[CMD] STATUS"));
    String s = String("OK STATUS strobe_intensity=") + strobeIntensity + " lamp_intensity=" + lampIntensity + " lamp=" + (lampOn ? "on" : "off");
    sendLine(client, s.c_str());
    return;
  }

  // Unknown
  Serial.print(F("[CMD] UNKNOWN -> "));
  Serial.println(cmd);
  sendLine(client, "ERR UNKNOWN CMD");
}

void setup() {
  Serial.begin(115200);
  delay(100);

  pinMode(ENC28J60_CS, OUTPUT);
  digitalWrite(ENC28J60_CS, HIGH);  // deselect for clean SPI

  pinMode(outputPin, OUTPUT);
  digitalWrite(outputPin, LOW);  // not used for now

  Ethernet.init(ENC28J60_CS);
  Ethernet.begin(mac, ip, dnsServer, gateway, subnet);
  server.begin();

  Serial.print(F("IP: "));
  Serial.println(Ethernet.localIP());
  Serial.print(F("Subnet: "));
  Serial.println(subnet);
  Serial.print(F("Gateway: "));
  Serial.println(gateway);
  auto link = Ethernet.linkStatus();
  Serial.print(F("Link: "));
  Serial.println(link == LinkON ? F("ON") : (link == LinkOFF ? F("OFF") : F("UNKNOWN")));
  Serial.print(F("TCP server listening on port "));
  Serial.println(PORT);
  Serial.println(F("Commands: LAMP ON | LAMP OFF | STROBE_INTENSITY <0..100> | LAMP_INTENSITY <0..100>"));
}

void loop() {
  EthernetClient client = server.available();
  if (!client) return;

  Serial.println(F("[NET] Client connected"));

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
  }

  client.stop();
  Serial.println(F("[NET] Client disconnected"));
}
