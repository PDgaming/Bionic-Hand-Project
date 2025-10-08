import sys
import cv2
import json
import numpy as np
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
)
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QImage, QPixmap
import mediapipe as mp
import serial


# --- Helpers ---
def _dist(p, q):
    return float(
        np.linalg.norm(np.array([p.x - q.x, p.y - q.y, p.z - q.z], dtype=np.float32))
    )


def compute_finger_metrics(landmarks):
    mp_hl = mp.solutions.hands.HandLandmark
    palm_width = (
        _dist(landmarks[mp_hl.INDEX_FINGER_MCP], landmarks[mp_hl.PINKY_MCP]) + 1e-6
    )

    # Curl distances
    finger_tips = {
        "thumb": (mp_hl.THUMB_TIP, mp_hl.THUMB_MCP),
        "index": (mp_hl.INDEX_FINGER_TIP, mp_hl.WRIST),
        "middle": (mp_hl.MIDDLE_FINGER_TIP, mp_hl.WRIST),
        "ring": (mp_hl.RING_FINGER_TIP, mp_hl.WRIST),
        "pinky": (mp_hl.PINKY_TIP, mp_hl.WRIST),
    }

    curls = {
        name: _dist(landmarks[tip], landmarks[base]) / palm_width
        for name, (tip, base) in finger_tips.items()
    }

    # Thumb rotation: distance between thumb PIP and pinky MCP
    thumb_rot = (
        _dist(landmarks[mp_hl.THUMB_TIP], landmarks[mp_hl.PINKY_MCP]) / palm_width
    )

    curls["thumb_rot"] = thumb_rot
    return curls


def normalize_curl(raw_value, min_val, max_val):
    if max_val == min_val or min_val is None or max_val is None:
        return 0.0
    return max(0.0, min(1.0, (raw_value - min_val) / (max_val - min_val)))


ser = serial.Serial("/dev/ttyACM0", 115200)


class HandTrackerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bionic Hand Tracker")
        self.setGeometry(100, 100, 800, 600)

        # --- MediaPipe setup ---
        self.mp_hands = mp.solutions.hands
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_styles = mp.solutions.drawing_styles

        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        self.cap = cv2.VideoCapture(0)

        # Calibration
        self.calibration_file = "finger_calibration.json"
        self.calibration = self.load_calibration()

        # --- GUI ---
        self.video_label = QLabel()
        self.curl_label = QLabel("Curls: N/A")

        self.open_btn = QPushButton("Calibrate Open Hand")
        self.closed_btn = QPushButton("Calibrate Closed Hand")
        self.save_btn = QPushButton("Save Calibration")
        self.recalibrate_btn = QPushButton("Re-Calibrate")

        self.open_btn.clicked.connect(lambda: self.calibrate("min"))
        self.closed_btn.clicked.connect(lambda: self.calibrate("max"))
        self.save_btn.clicked.connect(self.save_calibration)
        self.recalibrate_btn.clicked.connect(self.recalibrate)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.open_btn)
        btn_layout.addWidget(self.closed_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.recalibrate_btn)

        layout = QVBoxLayout()
        layout.addWidget(self.video_label)
        layout.addWidget(self.curl_label)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

        # Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)

    # --- Calibration ---
    def calibrate(self, mode):
        success, img = self.cap.read()
        if not success:
            return

        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.hands.process(img_rgb)
        if results.multi_hand_landmarks:
            curls = compute_finger_metrics(results.multi_hand_landmarks[0].landmark)
            for f in curls:
                self.calibration.setdefault(f, {})[mode] = curls[f]
            print(
                f"{mode.capitalize()} hand recorded:",
                {f: self.calibration[f][mode] for f in curls},
            )

            # Fix inverted calibration
            for f in self.calibration:
                if "min" in self.calibration[f] and "max" in self.calibration[f]:
                    if self.calibration[f]["min"] > self.calibration[f]["max"]:
                        self.calibration[f]["min"], self.calibration[f]["max"] = (
                            self.calibration[f]["max"],
                            self.calibration[f]["min"],
                        )

    def save_calibration(self):
        with open(self.calibration_file, "w") as f:
            json.dump(self.calibration, f, indent=2)
        print("Calibration saved to", self.calibration_file)

    def load_calibration(self):
        try:
            with open(self.calibration_file, "r") as f:
                return json.load(f)
        except:
            return {}

    def recalibrate(self):
        self.calibration = {}
        print("Calibration reset. Recalibrate your hand.")

    # --- Main loop ---
    def update_frame(self):
        success, frame = self.cap.read()
        if not success:
            return

        frame = cv2.flip(frame, 1)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(frame_rgb)

        # Draw on BGR frame for correct colors
        display_frame = frame.copy()

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                self.mp_drawing.draw_landmarks(
                    display_frame,
                    hand_landmarks,
                    self.mp_hands.HAND_CONNECTIONS,
                    self.mp_styles.get_default_hand_landmarks_style(),
                    self.mp_styles.get_default_hand_connections_style(),
                )

                curls = compute_finger_metrics(hand_landmarks.landmark)
                curls_normalized = {
                    f: normalize_curl(
                        curls[f],
                        self.calibration.get(f, {}).get("min"),
                        self.calibration.get(f, {}).get("max"),
                    )
                    for f in curls
                }

                thumb_pwm = int(curls_normalized["thumb"] * 255)
                index_pwm = int(curls_normalized["index"] * 255)
                middle_pwm = int(curls_normalized["middle"] * 255)
                ring_pwm = int(curls_normalized["ring"] * 255)
                pinky_pwm = int(curls_normalized["pinky"] * 255)
                thumb_rot_pwm = int(curls_normalized["thumb_rot"] * 255)

                self.curl_label.setText(
                    "Curls (0=open,1=closed): "
                    + " ".join([f"{k}:{v:.2f}" for k, v in curls_normalized.items()])
                )

                if ser:
                    ser.write(
                        f"{thumb_pwm},{index_pwm},{middle_pwm},{ring_pwm},{pinky_pwm},{thumb_rot_pwm}\n".encode()
                    )

        # Convert BGR -> RGB for QImage
        display_frame_rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = display_frame_rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(
            display_frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888
        )
        self.video_label.setPixmap(QPixmap.fromImage(qimg))

    def closeEvent(self, event):
        self.cap.release()
        self.hands.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = HandTrackerApp()
    window.show()
    sys.exit(app.exec_())
