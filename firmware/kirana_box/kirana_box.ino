/*
  Kirana Voice Ledger — counter box firmware (ESP32-S3, Arduino core 3.x)

  Hold the button, speak ("Ramesh ka 240 udhaar, 2 Aashirvaad 5kg bik gaye"), release.
  The box records 16 kHz / 16-bit mono from an INMP441, POSTs it as a WAV to the server's
  /voice endpoint, and plays the WAV reply through a MAX98357A amp.

  Board:   ESP32-S3 DevKitC-1 (N16R8 recommended: PSRAM holds up to MAX_SECONDS of audio)
  Arduino: Tools > PSRAM: "OPI PSRAM"; esp32 core >= 3.0 (uses ESP_I2S.h)

  Wiring (change in config.h):
    INMP441   VDD->3V3  GND->GND  L/R->GND  SCK->MIC_SCK  WS->MIC_WS  SD->MIC_SD
    MAX98357A VIN->5V   GND->GND  BCLK->AMP_BCLK  LRC->AMP_LRC  DIN->AMP_DIN  (GAIN unconnected = 9 dB)
    Button    one leg -> BUTTON_PIN, other leg -> GND (internal pull-up)
    Speaker   4–8 ohm, 2–3 W, across the MAX98357A +/- terminals

  LED (onboard RGB, if present): blue idle · red recording · amber thinking · green speaking · purple error

  STATUS: written against the arduino-esp32 3.x ESP_I2S API, NOT yet compiled or run on hardware.
*/
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ESP_I2S.h>
#include "config.h"

#ifndef SAMPLE_RATE
#define SAMPLE_RATE 16000
#endif

I2SClass mic;
I2SClass amp;

static uint8_t *recBuf = nullptr;   // 44-byte WAV header + PCM16
static size_t recCap = 0;           // bytes of PCM the buffer can hold
static uint8_t *rxBuf = nullptr;    // reply WAV
static size_t rxCap = 0;

// ---------------------------------------------------------------- LED
static void led(uint8_t r, uint8_t g, uint8_t b) {
#ifdef RGB_BUILTIN
  rgbLedWrite(RGB_BUILTIN, r / 4, g / 4, b / 4);
#endif
}

// ---------------------------------------------------------------- WAV helpers
static void put32(uint8_t *p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }
static void put16(uint8_t *p, uint16_t v) { p[0] = v; p[1] = v >> 8; }
static uint32_t get32(const uint8_t *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }
static uint16_t get16(const uint8_t *p) { return p[0] | (p[1] << 8); }

static void writeWavHeader(uint8_t *h, uint32_t pcmBytes) {
  memcpy(h, "RIFF", 4); put32(h + 4, 36 + pcmBytes); memcpy(h + 8, "WAVE", 4);
  memcpy(h + 12, "fmt ", 4); put32(h + 16, 16); put16(h + 20, 1); put16(h + 22, 1);
  put32(h + 24, SAMPLE_RATE); put32(h + 28, SAMPLE_RATE * 2); put16(h + 32, 2); put16(h + 34, 16);
  memcpy(h + 36, "data", 4); put32(h + 40, pcmBytes);
}

// ---------------------------------------------------------------- audio out
static void beep(int freq, int ms) {
  const int n = SAMPLE_RATE * ms / 1000;
  int16_t frame[256];
  int i = 0;
  amp.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_BOTH);
  while (i < n) {
    int k = 0;
    for (; k < 256 && i < n; k++, i++) frame[k] = (int16_t)(3000 * VOLUME * sinf(2 * PI * freq * i / SAMPLE_RATE));
    amp.write((uint8_t *)frame, k * 2);
  }
  amp.end();
}

static bool playWav(uint8_t *wav, size_t len) {
  if (len < 44 || memcmp(wav, "RIFF", 4) || memcmp(wav + 8, "WAVE", 4)) return false;
  uint32_t rate = SAMPLE_RATE; uint16_t ch = 1, bits = 16;
  size_t pos = 12; uint8_t *data = nullptr; uint32_t dataLen = 0;
  while (pos + 8 <= len) {                       // walk chunks: Sarvam's WAV may carry extra chunks
    uint32_t sz = get32(wav + pos + 4);
    if (!memcmp(wav + pos, "fmt ", 4)) { ch = get16(wav + pos + 10); rate = get32(wav + pos + 12); bits = get16(wav + pos + 22); }
    else if (!memcmp(wav + pos, "data", 4)) { data = wav + pos + 8; dataLen = min((size_t)sz, len - pos - 8); break; }
    pos += 8 + sz + (sz & 1);
  }
  if (!data || bits != 16) { Serial.printf("Unsupported WAV (bits=%u)\n", bits); return false; }
  Serial.printf("Playing %u bytes @ %lu Hz, %u ch\n", dataLen, rate, ch);

  int16_t *s = (int16_t *)data;                 // software volume
  for (uint32_t i = 0; i < dataLen / 2; i++) s[i] = (int16_t)(s[i] * VOLUME);

  amp.begin(I2S_MODE_STD, rate, I2S_DATA_BIT_WIDTH_16BIT, ch == 2 ? I2S_SLOT_MODE_STEREO : I2S_SLOT_MODE_MONO,
            I2S_STD_SLOT_BOTH);
  const size_t CH = 1024;
  for (uint32_t off = 0; off < dataLen; off += CH) amp.write(data + off, min((size_t)CH, (size_t)(dataLen - off)));
  int16_t zeros[256] = {0};                      // flush DMA so the tail isn't clipped
  for (int i = 0; i < 8; i++) amp.write((uint8_t *)zeros, sizeof(zeros));
  amp.end();
  return true;
}

// ---------------------------------------------------------------- audio in
static size_t recordWhileHeld() {
  int32_t raw[256];
  // discard ~100 ms so stale DMA audio and mic power-up noise don't lead the clip
  for (int i = 0; i < SAMPLE_RATE / 10 / 256 + 1; i++) mic.readBytes((char *)raw, sizeof(raw));

  int16_t *pcm = (int16_t *)(recBuf + 44);
  size_t n = 0, maxSamples = recCap / 2;
  while (digitalRead(BUTTON_PIN) == LOW && n < maxSamples) {
    size_t got = mic.readBytes((char *)raw, sizeof(raw)) / 4;
    for (size_t i = 0; i < got && n < maxSamples; i++) {
      int32_t v = raw[i] >> MIC_SHIFT;           // INMP441: 24-bit left-justified in a 32-bit slot
      pcm[n++] = (int16_t)constrain(v, -32768, 32767);
    }
  }
  return n * 2;
}

// ---------------------------------------------------------------- network
static void wifiConnect() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi");
  for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) { delay(250); Serial.print('.'); }
  if (WiFi.status() == WL_CONNECTED) Serial.printf(" ok %s\n", WiFi.localIP().toString().c_str());
  else Serial.println(" FAILED");
}

static size_t postAndReceive(size_t pcmBytes) {
  writeWavHeader(recBuf, pcmBytes);
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "audio/wav");
  const char *keep[] = {"X-Transcript", "X-Reply", "X-Lang"};
  http.collectHeaders(keep, 3);
  int code = http.POST(recBuf, 44 + pcmBytes);
  if (code != 200) {
    Serial.printf("POST failed: %d %s\n", code, http.errorToString(code).c_str());
    http.end();
    return 0;
  }
  Serial.println("Heard: " + http.header("X-Transcript"));   // URL-encoded
  Serial.println("Reply: " + http.header("X-Reply"));
  int total = http.getSize();                                  // -1 if chunked
  WiFiClient *st = http.getStreamPtr();
  size_t got = 0;
  uint32_t t0 = millis();
  while (http.connected() && (total < 0 || got < (size_t)total) && got < rxCap && millis() - t0 < HTTP_TIMEOUT_MS) {
    size_t avail = st->available();
    if (avail) got += st->readBytes(rxBuf + got, min(avail, rxCap - got));
    else delay(2);
  }
  http.end();
  return got;
}

// ---------------------------------------------------------------- main
void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  led(0, 0, 255);

  size_t want = (size_t)MAX_SECONDS * SAMPLE_RATE * 2;
  if (psramFound()) {
    recBuf = (uint8_t *)ps_malloc(44 + want); recCap = want;
    rxCap = 1024 * 1024; rxBuf = (uint8_t *)ps_malloc(rxCap);
  } else {                                                     // no PSRAM: ~4 s in, ~6 s out
    recCap = 4 * SAMPLE_RATE * 2; recBuf = (uint8_t *)malloc(44 + recCap);
    rxCap = 200 * 1024; rxBuf = (uint8_t *)malloc(rxCap);
  }
  if (!recBuf || !rxBuf) { Serial.println("Out of memory"); led(128, 0, 128); while (true) delay(1000); }

  mic.setPins(MIC_SCK, MIC_WS, -1, MIC_SD);                    // (bclk, ws, dout, din)
  if (!mic.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT))
    Serial.println("Mic I2S init failed");
  amp.setPins(AMP_BCLK, AMP_LRC, AMP_DIN, -1);

  wifiConnect();
  beep(880, 120);
  Serial.println("Ready. Hold the button and speak.");
}

void loop() {
  if (digitalRead(BUTTON_PIN) != LOW) { delay(10); return; }
  delay(25);                                                   // debounce
  if (digitalRead(BUTTON_PIN) != LOW) return;

  led(255, 0, 0);
  size_t pcm = recordWhileHeld();
  led(255, 120, 0);
  if (pcm < SAMPLE_RATE * 2 * 3 / 10) {                        // < 0.3 s: treat as an accidental tap
    led(0, 0, 255);
    return;
  }
  Serial.printf("Recorded %.1f s\n", pcm / (SAMPLE_RATE * 2.0));
  wifiConnect();
  size_t n = WiFi.status() == WL_CONNECTED ? postAndReceive(pcm) : 0;
  bool played = false;
  if (n) {
    led(0, 255, 0);
    played = playWav(rxBuf, n);
  }
  if (played) {
    led(0, 0, 255);
  } else {
    led(128, 0, 128);
    beep(220, 300);
    delay(400);
    led(0, 0, 255);
  }
  while (digitalRead(BUTTON_PIN) == LOW) delay(10);            // wait for release if still held at MAX_SECONDS
}
