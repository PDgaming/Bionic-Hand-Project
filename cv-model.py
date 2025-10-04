import cv2
import mediapipe as mp
import numpy as np

# --- Helpers ---


def _dist(p, q):
    """Euclidean distance between two 3D landmarks."""
    return float(np.linalg.norm(
        np.array([p.x - q.x, p.y - q.y, p.z - q.z], dtype=np.float32)
    ))


def compute_finger_curls(landmarks):
    """Return distance-based curl values for each finger."""
    mp_hl = mp.solutions.hands.HandLandmark

    # Palm width for normalization
    palm_width = _dist(landmarks[mp_hl.INDEX_FINGER_MCP],
                       landmarks[mp_hl.PINKY_MCP]) + 1e-6

    # Fingers: TIP to base (thumb uses CMC for better measurement)
    finger_tips = {
        "thumb": (mp_hl.THUMB_TIP, mp_hl.WRIST),
        "index": (mp_hl.INDEX_FINGER_TIP, mp_hl.WRIST),
        "middle": (mp_hl.MIDDLE_FINGER_TIP, mp_hl.WRIST),
        "ring": (mp_hl.RING_FINGER_TIP, mp_hl.WRIST),
        "pinky": (mp_hl.PINKY_TIP, mp_hl.WRIST),
    }

    curls = {}
    for name, (tip, base) in finger_tips.items():
        d = _dist(landmarks[tip], landmarks[base])
        curls[name] = d / palm_width  # normalize by palm width
    return curls

# --- Calibration ---


def calibrate_fingers(hands, cap):
    calibration = {finger: {"min": None, "max": None} for finger in ["thumb","index","middle","ring","pinky"]}
    print("Calibration: show OPEN hand and press 'o', then CLOSED hand and press 'c'.")

    # Warm-up camera
    for _ in range(10):
        cap.read()

    while True:
        success, img = cap.read()
        if not success:
            continue

        img = cv2.resize(img, (640, 480))
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = hands.process(img_rgb)

        display_img = img.copy()
        cv2.putText(display_img, "Press 'o' open, 'c' closed, 'q' quit",
                    (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)

        if results.multi_hand_landmarks:
            hand_landmarks = results.multi_hand_landmarks[0]
            mp_drawing.draw_landmarks(
                display_img,
                hand_landmarks,
                mp_hands.HAND_CONNECTIONS,
                mp_drawing_styles.get_default_hand_landmarks_style(),
                mp_drawing_styles.get_default_hand_connections_style()
            )
            curls = compute_finger_curls(hand_landmarks.landmark)

        cv2.imshow("Calibration", display_img)
        key = cv2.waitKey(1) & 0xFF

        if key == ord('o') and results.multi_hand_landmarks:
            for f in calibration:
                calibration[f]["min"] = curls[f]
            print("Open hand recorded:", {f: calibration[f]["min"] for f in calibration})

        elif key == ord('c') and results.multi_hand_landmarks:
            for f in calibration:
                calibration[f]["max"] = curls[f]
            print("Closed hand recorded:", {f: calibration[f]["max"] for f in calibration})

        elif key == ord('q'):
            break

    # Fix inverted calibration if needed
    for f in calibration:
        if calibration[f]["min"] is not None and calibration[f]["max"] is not None:
            if calibration[f]["min"] > calibration[f]["max"]:
                calibration[f]["min"], calibration[f]["max"] = calibration[f]["max"], calibration[f]["min"]

    cv2.destroyWindow("Calibration")
    return calibration


def normalize_curl(raw_value, min_val, max_val):
    """Normalize curl value 0=open, 1=closed."""
    if max_val == min_val or min_val is None or max_val is None:
        return 0.0
    return max(0.0, min(1.0, (raw_value - min_val) / (max_val - min_val)))

# --- MediaPipe setup ---


mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles

hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

cap = cv2.VideoCapture(0)

# --- Run calibration ---
calibration = calibrate_fingers(hands, cap)
print("Calibration finished. Values normalized 0..1.")

# --- Main loop ---
while True:
    success, img = cap.read()
    if not success:
        continue

    img = cv2.resize(img, (640, 480))
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    results = hands.process(img_rgb)
    display_img = img.copy()

    if results.multi_hand_landmarks:
        for hand_index, hand_landmarks in enumerate(results.multi_hand_landmarks):
            mp_drawing.draw_landmarks(
                display_img,
                hand_landmarks,
                mp_hands.HAND_CONNECTIONS,
                mp_drawing_styles.get_default_hand_landmarks_style(),
                mp_drawing_styles.get_default_hand_connections_style()
            )

            curls = compute_finger_curls(hand_landmarks.landmark)
            curls_normalized = {f: normalize_curl(curls[f], calibration[f]["min"], calibration[f]["max"])
                                for f in curls}

            label = f"Hand {hand_index}"
            if results.multi_handedness and hand_index < len(results.multi_handedness):
                label = results.multi_handedness[hand_index].classification[0].label

            print(f"{label} curls (0=open,1=closed): "
                  f"T:{curls_normalized['thumb']:.2f} "
                  f"I:{curls_normalized['index']:.2f} "
                  f"M:{curls_normalized['middle']:.2f} "
                  f"R:{curls_normalized['ring']:.2f} "
                  f"P:{curls_normalized['pinky']:.2f}")

    cv2.imshow("Hand Tracking", display_img)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
hands.close()
