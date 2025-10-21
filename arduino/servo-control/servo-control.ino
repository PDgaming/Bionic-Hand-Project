#include <Servo.h>

// --- Servo pins ---
const int servoPins[5] = {11, 10, 9, 6, 5}; // Index, middle, ring, pinky, thumb curl
const int thumbRotPin = 3;                   // Thumb rotation
Servo servos[5];
Servo thumbRotServo;

// --- Reverse flags ---
bool reversed[5] = {true, true, false, true, true}; // Per finger
int offset[5] = {0, 0, 0, 25, 0};                  // Offsets in degrees

// --- Input/angle ranges ---
const int INPUT_MIN = 0;
const int INPUT_MAX = 255;
const int ANGLE_MIN = 0;
const int ANGLE_MAX = 180;

// --- Thumb rotation custom range ---
const int THUMB_ROT_INPUT_MIN = 30;   // Safe min input from Python
const int THUMB_ROT_INPUT_MAX = 220;  // Safe max input from Python
const int THUMB_ROT_ANGLE_MIN = 0;
const int THUMB_ROT_ANGLE_MAX = 180;
int thumbRotOffset = 0; // optional offset for neutral position

void setup() {
  Serial.begin(115200);
  Serial.println("Ready to receive servo control data...");

  // Attach main finger servos
  for (int i = 0; i < 5; i++) {
    servos[i].attach(servoPins[i]);
    servos[i].write(90 + offset[i]); // Start at neutral + offset
  }

  // Attach thumb rotation servo
  thumbRotServo.attach(thumbRotPin);
  thumbRotServo.write(90 + thumbRotOffset); // Neutral
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();

    if (line.length() > 0) {
      Serial.print("Received: ");
      Serial.println(line);

      int values[6] = {0};
      int idx = 0;
      char* token = strtok((char*)line.c_str(), ",");

      while (token != NULL && idx < 6) {
        int raw = constrain(atoi(token), INPUT_MIN, INPUT_MAX);
        values[idx++] = raw;
        token = strtok(NULL, ",");
      }

      // --- Main finger servos ---
      if (idx >= 5) {
        for (int i = 0; i < 5; i++) {
          int angle = map(values[i], INPUT_MIN, INPUT_MAX, ANGLE_MIN, ANGLE_MAX);

          if (reversed[i]) {
            angle = ANGLE_MAX - angle;
          }

          angle = constrain(angle + offset[i], ANGLE_MIN, ANGLE_MAX);
          servos[i].write(angle);
        }
      }

      // --- Thumb rotation ---
      if (idx >= 6) {
        int thumbRotRaw = values[5];
        int thumbRotAngle = map(
          constrain(thumbRotRaw, THUMB_ROT_INPUT_MIN, THUMB_ROT_INPUT_MAX),
          THUMB_ROT_INPUT_MIN, THUMB_ROT_INPUT_MAX,
          THUMB_ROT_ANGLE_MIN, THUMB_ROT_ANGLE_MAX
        );
        thumbRotAngle = constrain(thumbRotAngle + thumbRotOffset, ANGLE_MIN, ANGLE_MAX);
        thumbRotServo.write(thumbRotAngle);
      }

      // --- Debug output ---
      Serial.print("Servo angles: ");
      for (int i = 0; i < 5; i++) {
        Serial.print(servos[i].read());
        Serial.print(", ");
      }
      Serial.print("ThumbRot: ");
      Serial.println(thumbRotServo.read());
    }
  }
}
