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
IPAddress ip(192, 168, 2, 70);
IPAddress dnsServer(192, 168, 2, 1);
IPAddress gateway(192, 168, 2, 1);
IPAddress subnet(255, 255, 255, 0);

const uint16_t PORT = 9000;
EthernetServer server(PORT);

// ---------- State ----------
uint8_t strobeIntensity = 0;  // 0..100
uint8_t lampIntensity   = 0;  // 0..100
bool lampOn = false;

// ---------- Forward decl ----------
void rs485_send_line(const String &s);
void rs485_poll(EthernetClient *client);

// ---------- TCP helpers ----------
void sendLine(EthernetClient &c, const char *s) {
  c.write((const uint8_t *)s, strlen(s));
  c.write('\n');
}

// Forward any line beginning with '~' over RS-485.
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
// Collect chars into a line buffer; on newline or idle timeout, print it.
void rs485_poll(EthernetClient *client) {
  static char    buf[160];
  static uint8_t idx = 0;
  static uint32_t lastByteMs = 0;
  const uint16_t idleFlushMs = 30;  // flush partial line after 30ms idle

  // Read all available chars
  while (RS485Serial.available()) {
    int b = RS485Serial.read();
    if (b < 0) break;
    lastByteMs = millis();

    char ch = (char)b;

    // Line termination
    if (ch == '\r' || ch == '\n') {
      if (idx > 0) {
        buf[idx] = '\0';
        // Print to Serial
        Serial.print(F("[RS485<-] "));
        Serial.println(buf);
        // Send to TCP client if connected
        if (client && client->connected()) {
          String out = String("RS485: ") + buf;
          sendLine(*client, out.c_str());
        }
        idx = 0;  // reset for next line
      }
      // swallow multiple CR/LF
      continue;
    }

    // Store normal char if space remains
    if (idx < sizeof(buf) - 1) {
      buf[idx++] = ch;
    } else {
      // Buffer full: terminate, emit, and reset
      buf[idx] = '\0';
      Serial.print(F("[RS485<-] "));
      Serial.println(buf);
      if (client && client->connected()) {
        String out = String("RS485: ") + buf;
        sendLine(*client, out.c_str());
      }
      idx = 0;
    }
  }

  // If we have a partial line and it's been idle for a while, flush it
  if (idx > 0 && (millis() - lastByteMs) > idleFlushMs) {
    buf[idx] = '\0';
    Serial.print(F("[RS485<-] "));
    Serial.println(buf);
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

  // 1) CUSTOM / RAW: forward "~..." to RS-485 and exit (no error)
  if (maybe_forward_rs485(cmd, client)) return;

  // 2) Known simulated commands

  // Lamp OFF
  if (cmd.equalsIgnoreCase("LAMP OFF")) {
    String data = "~device set lamp:000|SUBC24991";
    rs485_send_line(data);
    Serial.print("Data sent: "); Serial.println(data);

    lampOn = false;
    Serial.println(F("[CMD] LAMP OFF (simulated)"));
    sendLine(client, "OK LAMP OFF");
    return;
  }

  // Strobe Intensity
  if (cmd.startsWith("STROBE_INTENSITY")) {
    int sep = cmd.indexOf(' ');
    if (sep > 0) {
      int v = cmd.substring(sep + 1).toInt();
      if (v >= 0 && v <= 100) {
        strobeIntensity = (uint8_t)v;

        char buf[50];
        sprintf(buf, "~device set strobe:%03d|SUBC24991", strobeIntensity);
        String data = String(buf);

        rs485_send_line(data);
        Serial.print("Data sent: "); Serial.println(data);

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

  // Lamp Intensity
  if (cmd.startsWith("LAMP_INTENSITY")) {
    int sep = cmd.indexOf(' ');
    if (sep > 0) {
      int v = cmd.substring(sep + 1).toInt();
      if (v >= 0 && v <= 100) {
        lampIntensity = (uint8_t)v;

        char buf[50];
        sprintf(buf, "~device set lamp:%03d|SUBC24991", lampIntensity);
        String data = String(buf);

        rs485_send_line(data);
        Serial.print("Data sent: "); Serial.println(data);

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

  // Status
  if (cmd.equalsIgnoreCase("STATUS")) {
    String data = "~comms print status|SUBC24991";
    rs485_send_line(data);
    Serial.print("Data sent: "); Serial.println(data);

    Serial.println(F("[CMD] STATUS"));
    sendLine(client, "OK STATUS");
    return;
  }

  Serial.print(F("[CMD] UNKNOWN -> "));
  Serial.println(cmd);
  sendLine(client, "UNKNOWN CMD");
}

// ---------- RS-485 helpers ----------
void rs485_send_line(const String &s) {
  digitalWrite(RE, HIGH);  // disable receiver
  digitalWrite(DE, HIGH);  // enable driver
  delayMicroseconds(5);
  RS485Serial.print(s);
  RS485Serial.print("\r\n");
  RS485Serial.flush();
  delayMicroseconds(5);
  digitalWrite(DE, LOW);  // back to receive
  digitalWrite(RE, LOW);
}

void setup() {
  Serial.begin(9600);

  // RS-485 start (match peer baud rate)
  RS485Serial.begin(9600);
  pinMode(DE, OUTPUT);
  pinMode(RE, OUTPUT);
  digitalWrite(DE, LOW);  // start in receive
  digitalWrite(RE, LOW);
  Serial.println("RS-485 sender/monitor ready.");

  // Ethernet start
  pinMode(ENC28J60_CS, OUTPUT);
  digitalWrite(ENC28J60_CS, HIGH);  // deselect for clean SPI
  Ethernet.init(ENC28J60_CS);
  Ethernet.begin(mac, ip, dnsServer, gateway, subnet);
  server.begin();

  Serial.print(F("IP: "));      Serial.println(Ethernet.localIP());
  Serial.print(F("Subnet: "));  Serial.println(subnet);
  Serial.print(F("Gateway: ")); Serial.println(gateway);
  auto link = Ethernet.linkStatus();
  Serial.print(F("Link: "));
  Serial.println(link == LinkON ? F("ON") : (link == LinkOFF ? F("OFF") : F("UNKNOWN")));
  Serial.print(F("TCP server listening on port ")); Serial.println(PORT);
  Serial.println(F("Commands:"));
  Serial.println(F("  ~... (forwarded to RS-485)"));
  Serial.println(F("  LAMP OFF | STROBE_INTENSITY <0..100> | LAMP_INTENSITY <0..100> | STATUS"));
}

void loop() {
  // Always poll RS-485 (even with no client)
  rs485_poll(nullptr);

  // Accept a client if available
  EthernetClient client = server.available();
  if (!client) return;

  Serial.println(F("[NET] Client connected"));

  String line = "";
  while (client.connected()) {
    // Handle incoming TCP data
    while (client.available()) {
      char ch = client.read();
      if (ch == '\n') {
        handleCommand(line, client);
        line = "";
      } else if (ch != '\r') {
        if (line.length() < 120) line += ch;
      }
    }

    // While client is connected, also stream RS-485 to them
    rs485_poll(&client);
  }

  client.stop();
  Serial.println(F("[NET] Client disconnected"));
}
