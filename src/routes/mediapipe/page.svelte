<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';

	let videoElement: HTMLVideoElement;
	let canvasElement: HTMLCanvasElement;
	let canvasCtx: any;
	let handLandmarker: any;
	let isTracking = false;
	let fingerCurls: any = null;
	let normalizedCurls: any = null;
	let handsDetected = 0;
	let animationId: any;
	let lastVideoTime = -1;
	let calibration: any = {};
	const CALIBRATION_KEY = 'hand_calibration_data';

	// Serial communication variables
	let port: any = null;
	let writer: any = null;
	let reader: any = null;
	let isConnecting = false;
	let serialError: string | null = null;
	let receivedData = 'Waiting for data...';
	let isSerialConnected = false;

	// MediaPipe hand landmark indices
	const HandLandmark = {
		WRIST: 0,
		THUMB_CMC: 1,
		THUMB_MCP: 2,
		THUMB_IP: 3,
		THUMB_TIP: 4,
		INDEX_FINGER_MCP: 5,
		INDEX_FINGER_PIP: 6,
		INDEX_FINGER_DIP: 7,
		INDEX_FINGER_TIP: 8,
		MIDDLE_FINGER_MCP: 9,
		MIDDLE_FINGER_PIP: 10,
		MIDDLE_FINGER_DIP: 11,
		MIDDLE_FINGER_TIP: 12,
		RING_FINGER_MCP: 13,
		RING_FINGER_PIP: 14,
		RING_FINGER_DIP: 15,
		RING_FINGER_TIP: 16,
		PINKY_MCP: 17,
		PINKY_PIP: 18,
		PINKY_DIP: 19,
		PINKY_TIP: 20
	};

	// Calculate 3D distance between two landmarks (matching Python _dist)
	function dist(p: any, q: any): number {
		const dx = p.x - q.x;
		const dy = p.y - q.y;
		const dz = (p.z || 0) - (q.z || 0);
		return Math.sqrt(dx * dx + dy * dy + dz * dz);
	}

	// Compute finger curl metrics (matching Python compute_finger_metrics)
	function computeFingerMetrics(landmarks: any) {
		const palmWidth =
			dist(landmarks[HandLandmark.INDEX_FINGER_MCP], landmarks[HandLandmark.PINKY_MCP]) + 1e-6;

		const fingerTips = {
			thumb: { tip: HandLandmark.THUMB_TIP, base: HandLandmark.THUMB_MCP },
			index: { tip: HandLandmark.INDEX_FINGER_TIP, base: HandLandmark.WRIST },
			middle: { tip: HandLandmark.MIDDLE_FINGER_TIP, base: HandLandmark.WRIST },
			ring: { tip: HandLandmark.RING_FINGER_TIP, base: HandLandmark.WRIST },
			pinky: { tip: HandLandmark.PINKY_TIP, base: HandLandmark.WRIST }
		};

		const curls: any = {};
		for (const [name, { tip, base }] of Object.entries(fingerTips)) {
			curls[name] = dist(landmarks[tip], landmarks[base]) / palmWidth;
		}

		const thumbRot =
			dist(landmarks[HandLandmark.THUMB_TIP], landmarks[HandLandmark.PINKY_MCP]) / palmWidth;

		curls.thumb_rot = thumbRot;

		return curls;
	}

	// Normalize curl value (matching Python normalize_curl)
	function normalizeCurl(rawValue: number, minVal: number | null, maxVal: number | null): number {
		if (maxVal === minVal || minVal === null || maxVal === null) {
			return 0.0;
		}
		return Math.max(0.0, Math.min(1.0, (rawValue - minVal) / (maxVal - minVal)));
	}

	// Load calibration from localStorage
	function loadCalibration() {
		if (!browser) return {};
		try {
			const saved = localStorage.getItem(CALIBRATION_KEY);
			return saved ? JSON.parse(saved) : {};
		} catch {
			return {};
		}
	}

	// Save calibration to localStorage
	function saveCalibration() {
		if (!browser) return;
		localStorage.setItem(CALIBRATION_KEY, JSON.stringify(calibration));
		console.log('Calibration saved:', calibration);
		alert('Calibration saved successfully!');
	}

	// Calibrate current hand position
	function calibrate(mode: 'min' | 'max') {
		if (!fingerCurls) {
			alert('No hand detected! Please show your hand to the camera.');
			return;
		}

		for (const finger in fingerCurls) {
			if (!calibration[finger]) {
				calibration[finger] = {};
			}
			calibration[finger][mode] = fingerCurls[finger];
		}

		// Fix inverted calibration (matching Python logic)
		for (const finger in calibration) {
			if (calibration[finger].min !== undefined && calibration[finger].max !== undefined) {
				if (calibration[finger].min > calibration[finger].max) {
					[calibration[finger].min, calibration[finger].max] = [
						calibration[finger].max,
						calibration[finger].min
					];
				}
			}
		}

		console.log(
			`${mode.charAt(0).toUpperCase() + mode.slice(1)} hand recorded:`,
			Object.fromEntries(
				Object.entries(calibration).map(([f, vals]: [string, any]) => [f, vals[mode]])
			)
		);

		alert(`${mode === 'min' ? 'Open' : 'Closed'} hand position recorded!`);
	}

	// Reset calibration
	function recalibrate() {
		calibration = {};
		if (browser) {
			localStorage.removeItem(CALIBRATION_KEY);
		}
		console.log('Calibration reset. Please recalibrate your hand.');
		alert('Calibration reset! Please recalibrate by capturing open and closed hand positions.');
	}

	// --- Serial Communication Functions ---

	async function connectSerial() {
		if (!browser || !('serial' in navigator)) {
			serialError = 'Web Serial API not supported in this browser';
			return;
		}

		isConnecting = true;
		serialError = null;

		try {
			port = await (navigator as any).serial.requestPort();
			await port.open({ baudRate: 115200 }); // Match Arduino baudRate

			// Setup the writer (to send data to Arduino)
			const encoder = new TextEncoderStream();
			const writableStreamClosed = encoder.readable.pipeTo(port.writable);
			writer = encoder.writable.getWriter();

			// Setup the reader (to receive data from Arduino)
			const decoder = new TextDecoderStream();
			port.readable.pipeTo(decoder.writable);
			reader = decoder.readable.getReader();

			isSerialConnected = true;
			readLoop(); // Start reading from Arduino
			console.log('Serial connected at 115200 baud');
		} catch (e: any) {
			serialError = e.message;
			console.error('Serial connection error:', e);
		} finally {
			isConnecting = false;
		}
	}

	async function readLoop() {
		try {
			while (true) {
				const { value, done } = await reader.read();
				if (done) {
					reader.releaseLock();
					break;
				}
				receivedData = value.trim();
			}
		} catch (e) {
			console.error('Read loop error:', e);
		}
	}

	async function sendSerialData(data: string) {
		if (writer) {
			try {
				await writer.write(data + '\n');
			} catch (e) {
				console.error('Send error:', e);
			}
		}
	}

	async function disconnectSerial() {
		if (reader) {
			await reader.cancel();
			reader.releaseLock();
			reader = null;
		}
		if (writer) {
			await writer.close();
			writer.releaseLock();
			writer = null;
		}
		if (port) {
			await port.close();
			port = null;
		}
		isSerialConnected = false;
		receivedData = 'Waiting for data...';
		console.log('Serial disconnected');
	}

	// Send PWM values to Arduino
	function sendToArduino() {
		if (!isSerialConnected || !normalizedCurls) return;

		// Convert normalized curls to PWM (0-255)
		// Order: thumb, index, middle, ring, pinky, thumb_rot
		const thumbPWM = Math.round(normalizedCurls.thumb * 255);
		const indexPWM = Math.round(normalizedCurls.index * 255);
		const middlePWM = Math.round(normalizedCurls.middle * 255);
		const ringPWM = Math.round(normalizedCurls.ring * 255);
		const pinkyPWM = Math.round(normalizedCurls.pinky * 255);
		const thumbRotPWM = Math.round(normalizedCurls.thumb_rot * 255);

		// Format: "thumb,index,middle,ring,pinky,thumb_rot"
		const message = `${thumbPWM},${indexPWM},${middlePWM},${ringPWM},${pinkyPWM},${thumbRotPWM}`;
		sendSerialData(message);
	}

	// --- MediaPipe Setup ---

	onMount(async () => {
		if (!browser) return;

		canvasCtx = canvasElement.getContext('2d');
		calibration = loadCalibration();
		await initializeHandLandmarker();

		return () => {
			if (animationId) {
				cancelAnimationFrame(animationId);
			}
			stopVideo();
			if (isSerialConnected) {
				disconnectSerial();
			}
		};
	});

	async function initializeHandLandmarker() {
		try {
			const { HandLandmarker, FilesetResolver } = await import('@mediapipe/tasks-vision');

			const vision = await FilesetResolver.forVisionTasks(
				'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm'
			);

			handLandmarker = await HandLandmarker.createFromOptions(vision, {
				baseOptions: {
					modelAssetPath:
						'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
					delegate: 'CPU'
				},
				runningMode: 'VIDEO',
				numHands: 2,
				minHandDetectionConfidence: 0.5,
				minHandPresenceConfidence: 0.5,
				minTrackingConfidence: 0.5
			});

			console.log('HandLandmarker initialized with CPU delegate');
		} catch (error) {
			console.error('Error initializing HandLandmarker:', error);
		}
	}

	let cameraPermissionGranted = false;

	async function requestCameraPermission() {
		try {
			const stream = await navigator.mediaDevices.getUserMedia({ video: true });
			stream.getTracks().forEach((track) => track.stop());
			cameraPermissionGranted = true;
			console.log('Camera permission granted');
		} catch (e) {
			console.error('Permission denied:', e);
			cameraPermissionGranted = false;
		}
	}

	async function startTracking() {
		try {
			// Simply request video stream - Chrome will handle device selection
			console.log('Requesting camera access...');

			const stream = await navigator.mediaDevices.getUserMedia({
				video: {
					width: { ideal: 640 },
					height: { ideal: 480 }
				}
			});

			console.log('Stream obtained successfully');
			const videoTrack = stream.getVideoTracks()[0];
			console.log('Video track label:', videoTrack.label);
			console.log('Video track settings:', videoTrack.getSettings());

			videoElement.srcObject = stream;

			// Wait for video metadata and ensure it's playing
			await new Promise((resolve, reject) => {
				const timeout = setTimeout(() => {
					reject(new Error('Video loading timeout'));
				}, 10000); // 10 second timeout

				videoElement.onloadedmetadata = async () => {
					clearTimeout(timeout);
					console.log('Video metadata loaded');
					console.log('Video dimensions:', videoElement.videoWidth, 'x', videoElement.videoHeight);

					try {
						await videoElement.play();
						console.log('Video playing');

						// Wait a bit more to ensure first frame is rendered
						setTimeout(() => {
							resolve(null);
						}, 100);
					} catch (e) {
						reject(e);
					}
				};

				videoElement.onerror = () => {
					clearTimeout(timeout);
					reject(new Error('Video element error'));
				};
			});

			isTracking = true;
			predictWebcam();
			console.log('Camera started successfully');
		} catch (error: any) {
			console.error('Error accessing webcam:', error);
			let errorMessage = 'Could not access camera.\n\n';

			if (error.name === 'NotFoundError') {
				errorMessage += 'Camera not detected by Chrome.\n\n';
				errorMessage += 'For OBS Virtual Camera:\n';
				errorMessage += '• Make sure OBS Virtual Camera is started\n';
				errorMessage += '• Restart Chrome completely (close all windows)\n';
				errorMessage += '• Try chrome://settings/content/camera to verify the camera is visible\n';
				errorMessage += '• Some virtual cameras need a Chrome restart to be detected';
			} else if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
				errorMessage += 'Camera permission denied.\n\n';
				errorMessage += '• Click the camera icon in the address bar\n';
				errorMessage += '• Select "Always allow" for camera access\n';
				errorMessage += '• Make sure to select "OBS Virtual Camera" from the dropdown\n';
				errorMessage += '• Refresh the page after granting permission';
			} else if (error.name === 'NotReadableError') {
				errorMessage += 'Camera is already in use.\n\n';
				errorMessage += '• Close other tabs/apps using the camera\n';
				errorMessage += '• Restart OBS Virtual Camera\n';
				errorMessage += '• Check if another browser window has camera access';
			} else {
				errorMessage += 'Error: ' + error.message;
			}

			alert(errorMessage);
		}
	}

	function predictWebcam() {
		if (!isTracking) return;

		const nowInMs = Date.now();

		// Check if video is ready and has valid dimensions
		if (
			videoElement.readyState < 2 ||
			videoElement.videoWidth === 0 ||
			videoElement.videoHeight === 0
		) {
			console.log('Video not ready yet, waiting...');
			animationId = requestAnimationFrame(predictWebcam);
			return;
		}

		if (videoElement.currentTime !== lastVideoTime) {
			lastVideoTime = videoElement.currentTime;

			try {
				const results = handLandmarker.detectForVideo(videoElement, nowInMs);

				// Clear canvas
				canvasCtx.save();
				canvasCtx.clearRect(0, 0, canvasElement.width, canvasElement.height);

				// Draw video frame (flipped)
				canvasCtx.scale(-1, 1);
				canvasCtx.drawImage(
					videoElement,
					-canvasElement.width,
					0,
					canvasElement.width,
					canvasElement.height
				);
				canvasCtx.restore();

				if (results.landmarks && results.landmarks.length > 0) {
					handsDetected = results.landmarks.length;

					// Calculate finger curls for first hand
					fingerCurls = computeFingerMetrics(results.landmarks[0]);

					// Normalize curls if calibration exists
					normalizedCurls = {};
					for (const finger in fingerCurls) {
						normalizedCurls[finger] = normalizeCurl(
							fingerCurls[finger],
							calibration[finger]?.min ?? null,
							calibration[finger]?.max ?? null
						);
					}

					// Send to Arduino if connected
					if (isSerialConnected && Object.keys(calibration).length > 0) {
						sendToArduino();
					}

					// Draw landmarks for all hands
					for (const handLandmarks of results.landmarks) {
						drawConnectors(handLandmarks);
						drawLandmarks(handLandmarks);
					}
				} else {
					handsDetected = 0;
					fingerCurls = null;
					normalizedCurls = null;
				}
			} catch (error) {
				console.error('Error in predictWebcam:', error);
			}
		}

		animationId = requestAnimationFrame(predictWebcam);
	}

	function drawConnectors(landmarks: any) {
		const connections = [
			[0, 1],
			[1, 2],
			[2, 3],
			[3, 4],
			[0, 5],
			[5, 6],
			[6, 7],
			[7, 8],
			[0, 9],
			[9, 10],
			[10, 11],
			[11, 12],
			[0, 13],
			[13, 14],
			[14, 15],
			[15, 16],
			[0, 17],
			[17, 18],
			[18, 19],
			[19, 20],
			[5, 9],
			[9, 13],
			[13, 17]
		];

		canvasCtx.strokeStyle = '#00FF00';
		canvasCtx.lineWidth = 2;

		for (const [start, end] of connections) {
			const startPoint = landmarks[start];
			const endPoint = landmarks[end];

			canvasCtx.beginPath();
			canvasCtx.moveTo(startPoint.x * canvasElement.width, startPoint.y * canvasElement.height);
			canvasCtx.lineTo(endPoint.x * canvasElement.width, endPoint.y * canvasElement.height);
			canvasCtx.stroke();
		}
	}

	function drawLandmarks(landmarks: any) {
		canvasCtx.fillStyle = '#FF0000';

		for (const landmark of landmarks) {
			const x = landmark.x * canvasElement.width;
			const y = landmark.y * canvasElement.height;

			canvasCtx.beginPath();
			canvasCtx.arc(x, y, 3, 0, 2 * Math.PI);
			canvasCtx.fill();
		}
	}

	function stopTracking() {
		isTracking = false;
		if (animationId) {
			cancelAnimationFrame(animationId);
		}
		stopVideo();
	}

	function stopVideo() {
		if (videoElement && videoElement.srcObject) {
			const tracks = videoElement.srcObject.getTracks();
			tracks.forEach((track) => track.stop());
			videoElement.srcObject = null;
		}
	}
</script>

<div class="container">
	<h2>Bionic Hand Controller</h2>

	<!-- Serial Connection Section -->
	<div class="serial-section">
		<h3>Arduino Connection</h3>
		<div class="serial-controls">
			<button
				on:click={isSerialConnected ? disconnectSerial : connectSerial}
				class={isSerialConnected ? 'btn-danger' : 'btn-success'}
				disabled={isConnecting}
			>
				{#if isSerialConnected}
					Disconnect Arduino
				{:else if isConnecting}
					Connecting...
				{:else}
					Connect to Arduino
				{/if}
			</button>

			{#if isSerialConnected}
				<span class="status-indicator connected">● Connected</span>
			{:else}
				<span class="status-indicator disconnected">● Disconnected</span>
			{/if}
		</div>

		{#if serialError}
			<p class="error-message">Error: {serialError}</p>
		{/if}

		{#if isSerialConnected}
			<div class="arduino-data">
				<h4>Arduino Response:</h4>
				<pre>{receivedData}</pre>
			</div>
		{/if}
	</div>

	<!-- Video Section -->
	<div class="video-container">
		<video bind:this={videoElement} class="input-video" autoplay playsinline></video>
		<canvas bind:this={canvasElement} class="output-canvas" width="640" height="480"></canvas>
	</div>

	<!-- Tracking Controls -->
	<div class="controls">
		{#if !isTracking}
			<button on:click={startTracking} class="btn-primary">Start Tracking</button>
		{:else}
			<button on:click={stopTracking} class="btn-danger">Stop Tracking</button>
		{/if}
	</div>

	<!-- Calibration Controls -->
	<div class="calibration-controls">
		<button on:click={() => calibrate('min')} class="btn-secondary" disabled={!isTracking}>
			Calibrate Open Hand
		</button>
		<button on:click={() => calibrate('max')} class="btn-secondary" disabled={!isTracking}>
			Calibrate Closed Hand
		</button>
		<button
			on:click={saveCalibration}
			class="btn-success"
			disabled={Object.keys(calibration).length === 0}
		>
			Save Calibration
		</button>
		<button on:click={recalibrate} class="btn-warning"> Reset Calibration </button>
	</div>

	{#if isTracking}
		<div class="info">
			<p>✓ Running on CPU</p>
			<p>Hands detected: {handsDetected}</p>
			{#if isSerialConnected && Object.keys(calibration).length > 0}
				<p class="sending-data">📡 Sending data to Arduino</p>
			{/if}
		</div>
	{/if}

	<!-- Finger Curl Values -->
	{#if fingerCurls}
		<div class="curl-values">
			<h3>Finger Curl Values</h3>

			<div class="values-section">
				<h4>Raw Values (Distance Ratios)</h4>
				<div class="curl-grid">
					{#each Object.entries(fingerCurls) as [finger, value]}
						<div class="curl-item">
							<span class="finger-name">{finger.replace('_', ' ')}:</span>
							<span class="curl-value">{value.toFixed(3)}</span>
						</div>
					{/each}
				</div>
			</div>

			{#if normalizedCurls && Object.keys(calibration).length > 0}
				<div class="values-section">
					<h4>Normalized Values (0=open, 1=closed)</h4>
					<div class="curl-grid">
						{#each Object.entries(normalizedCurls) as [finger, value]}
							<div class="curl-item normalized">
								<span class="finger-name">{finger.replace('_', ' ')}:</span>
								<span class="curl-value">{value.toFixed(2)}</span>
								<div class="progress-bar">
									<div class="progress-fill" style="width: {value * 100}%"></div>
								</div>
							</div>
						{/each}
					</div>
				</div>

				<div class="pwm-values">
					<h4>PWM Values (0-255) - Sent to Arduino</h4>
					<div class="pwm-grid">
						<div class="pwm-item">Thumb: {Math.round(normalizedCurls.thumb * 255)}</div>
						<div class="pwm-item">Index: {Math.round(normalizedCurls.index * 255)}</div>
						<div class="pwm-item">Middle: {Math.round(normalizedCurls.middle * 255)}</div>
						<div class="pwm-item">Ring: {Math.round(normalizedCurls.ring * 255)}</div>
						<div class="pwm-item">Pinky: {Math.round(normalizedCurls.pinky * 255)}</div>
						<div class="pwm-item">Thumb Rot: {Math.round(normalizedCurls.thumb_rot * 255)}</div>
					</div>
				</div>
			{:else}
				<p class="note calibration-needed">
					⚠️ No calibration data. Please calibrate by showing your open hand and clicking "Calibrate
					Open Hand", then showing your closed fist and clicking "Calibrate Closed Hand".
				</p>
			{/if}

			<p class="note">
				Lower raw values typically indicate more curl. Calibration normalizes these to 0-1 range.
			</p>
		</div>
	{/if}
</div>

<style>
	.container {
		max-width: 900px;
		margin: 0 auto;
		padding: 20px;
		font-family: Arial, sans-serif;
	}

	h2 {
		text-align: center;
		color: #333;
		margin-bottom: 20px;
	}

	h3 {
		color: #333;
		margin-bottom: 15px;
		font-size: 20px;
	}

	h4 {
		color: #555;
		margin-bottom: 12px;
		font-size: 16px;
		margin-top: 20px;
	}

	/* Serial Section */
	.serial-section {
		background-color: #f5f5f5;
		padding: 20px;
		border-radius: 8px;
		margin-bottom: 20px;
	}

	.serial-controls {
		display: flex;
		align-items: center;
		gap: 15px;
		margin-bottom: 10px;
	}

	.status-indicator {
		font-weight: bold;
		font-size: 14px;
	}

	.status-indicator.connected {
		color: #4caf50;
	}

	.status-indicator.disconnected {
		color: #999;
	}

	.error-message {
		color: #f44336;
		margin-top: 10px;
		padding: 10px;
		background-color: #ffebee;
		border-radius: 4px;
	}

	.arduino-data {
		margin-top: 15px;
		padding: 10px;
		background-color: #fff;
		border-radius: 4px;
		border: 1px solid #ddd;
	}

	.arduino-data pre {
		margin: 5px 0 0 0;
		font-family: 'Courier New', monospace;
		font-size: 12px;
		color: #333;
		white-space: pre-wrap;
	}

	/* Video Section */
	.video-container {
		position: relative;
		width: 640px;
		height: 480px;
		margin: 0 auto;
	}

	.input-video {
		display: none;
	}

	.output-canvas {
		width: 100%;
		height: 100%;
		border: 2px solid #333;
		border-radius: 8px;
		background-color: #000;
	}

	/* Controls */
	.controls {
		text-align: center;
		margin-top: 20px;
	}

	.calibration-controls {
		display: flex;
		justify-content: center;
		gap: 10px;
		margin-top: 15px;
		flex-wrap: wrap;
	}

	button {
		padding: 12px 20px;
		font-size: 14px;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		transition: all 0.3s;
		font-weight: 500;
	}

	button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-primary {
		background-color: #4caf50;
	}

	.btn-primary:hover:not(:disabled) {
		background-color: #45a049;
	}

	.btn-danger {
		background-color: #f44336;
	}

	.btn-danger:hover:not(:disabled) {
		background-color: #da190b;
	}

	.btn-secondary {
		background-color: #2196f3;
	}

	.btn-secondary:hover:not(:disabled) {
		background-color: #0b7dda;
	}

	.btn-success {
		background-color: #4caf50;
	}

	.btn-success:hover:not(:disabled) {
		background-color: #45a049;
	}

	.btn-warning {
		background-color: #ff9800;
	}

	.btn-warning:hover:not(:disabled) {
		background-color: #e68900;
	}

	/* Info Section */
	.info {
		margin-top: 20px;
		padding: 15px;
		background-color: #f0f0f0;
		border-radius: 4px;
		text-align: center;
	}

	.info p {
		margin: 5px 0;
		color: #555;
	}

	.sending-data {
		color: #4caf50;
		font-weight: bold;
		animation: pulse 1.5s ease-in-out infinite;
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.6;
		}
	}

	/* Curl Values */
	.curl-values {
		margin-top: 20px;
		padding: 20px;
		background-color: white;
		border-radius: 8px;
		box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
	}

	.values-section {
		margin-bottom: 20px;
	}

	.curl-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 12px;
		margin-bottom: 15px;
	}

	.curl-item {
		padding: 12px;
		background-color: #f8f8f8;
		border-radius: 4px;
	}

	.curl-item.normalized {
		background-color: #e3f2fd;
	}

	.progress-bar {
		margin-top: 6px;
		height: 8px;
		background-color: #ddd;
		border-radius: 4px;
		overflow: hidden;
	}

	.progress-fill {
		height: 100%;
		background: linear-gradient(90deg, #4caf50, #2196f3);
		transition: width 0.1s ease;
	}

	.pwm-values {
		margin-top: 20px;
		padding: 15px;
		background-color: #fff3e0;
		border-radius: 4px;
		border-left: 4px solid #ff9800;
	}

	.pwm-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 10px;
		margin-top: 10px;
	}

	.pwm-item {
		padding: 8px;
		background-color: white;
		border-radius: 4px;
		font-family: 'Courier New', monospace;
		font-weight: bold;
		color: #ff9800;
		text-align: center;
	}

	.finger-name {
		font-weight: 600;
		color: #555;
		text-transform: capitalize;
	}

	.curl-value {
		margin-left: 8px;
		color: #2196f3;
		font-family: 'Courier New', monospace;
		font-weight: bold;
	}

	.note {
		font-size: 12px;
		color: #666;
		font-style: italic;
		margin-top: 15px;
	}

	.calibration-needed {
		background-color: #fff3cd;
		padding: 12px;
		border-radius: 4px;
		border-left: 4px solid #ffc107;
		font-style: normal;
		color: #856404;
	}
</style>
