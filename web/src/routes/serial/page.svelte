<script>
	let port;
	let writer;
	let reader;
	let receivedData = 'Waiting for data...';
	let isConnecting = false;
	let error = null;

	// --- 1. Connection and Setup ---
	async function connect() {
		isConnecting = true;
		error = null;
		try {
			port = await navigator.serial.requestPort();
			await port.open({ baudRate: 9600 });

			// Setup the writer (to send data to Arduino)
			const encoder = new TextEncoderStream();
			const writableStreamClosed = encoder.readable.pipeTo(port.writable);
			writer = encoder.writable.getWriter();

			// Setup the reader (to receive data from Arduino)
			// We use a TextDecoderStream to convert the byte stream into readable strings
			const decoder = new TextDecoderStream();
			port.readable.pipeTo(decoder.writable);
			reader = decoder.readable.getReader();

			readLoop(); // Start the reading loop immediately after connection

			console.log('Connected and reading started!');
		} catch (e) {
			error = e.message;
			console.error(e);
		} finally {
			isConnecting = false;
		}
	}

	// --- 2. The Reading Loop ---
	async function readLoop() {
		while (true) {
			const { value, done } = await reader.read();
			if (done) {
				// Allow the user to reconnect if the port is closed
				reader.releaseLock();
				break;
			}
			// Update the Svelte variable with the new data
			receivedData = value.trim();
		}
	}

	// --- 3. Sending Data ---
	async function sendData(data) {
		if (writer) {
			await writer.write(data + '\n');
		}
	}

	// --- 4. Disconnect (Important for cleanup) ---
	async function disconnect() {
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
		receivedData = 'Waiting for data...';
		console.log('Disconnected.');
	}
</script>

<main>
	<h1>Arduino Serial Communication</h1>

	<button on:click={port ? disconnect : connect} disabled={isConnecting}>
		{#if port}
			Disconnect
		{:else}
			{isConnecting ? 'Connecting...' : 'Connect to Arduino'}
		{/if}
	</button>

	{#if port}
		<h2>Control and Status</h2>
		<button on:click={() => sendData('READ_SENSOR')}>Request Sensor Data</button>
		<button on:click={() => sendData('TOGGLE_LED')}>Toggle LED</button>
	{/if}

	<h2>Data From Arduino:</h2>
	<p class="data-display">{receivedData}</p>

	{#if error}
		<p style="color: red;">Connection Error: {error}</p>
	{/if}
</main>
