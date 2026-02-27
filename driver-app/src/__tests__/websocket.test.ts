/**
 * Tests for WebSocketClient reconnect logic and message parsing.
 *
 * Uses a mock WebSocket implementation so no real network connection is needed.
 */

import {WebSocketClient} from '../services/websocket';

// ---------------------------------------------------------------------------
// Mock WebSocket
// ---------------------------------------------------------------------------

type WsListener = (event: Event | MessageEvent | CloseEvent) => void;

class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;

  readyState: number = MockWebSocket.OPEN;
  url: string;
  onopen: WsListener | null = null;
  onmessage: WsListener | null = null;
  onerror: WsListener | null = null;
  onclose: WsListener | null = null;

  sentMessages: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    // Simulate async open
    setTimeout(() => this.onopen?.(new Event('open')), 0);
  }

  send(data: string): void {
    this.sentMessages.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close', {code: 1000, reason: 'normal'}));
  }

  // Test helpers
  simulateMessage(data: string): void {
    this.onmessage?.(new MessageEvent('message', {data}));
  }

  simulateClose(code = 1006): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close', {code}));
  }

  static instances: MockWebSocket[] = [];
  static reset(): void {
    MockWebSocket.instances = [];
  }
}

(global as unknown as {WebSocket: typeof MockWebSocket}).WebSocket = MockWebSocket;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function flushTimers(): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, 0));
}

// ---------------------------------------------------------------------------
// backoffDelayMs
// ---------------------------------------------------------------------------

describe('WebSocketClient.backoffDelayMs', () => {
  let client: WebSocketClient;

  beforeEach(() => {
    client = new WebSocketClient();
  });

  test('retry 0 → delay in [1000, 1200] ms range', () => {
    const delay = client.backoffDelayMs(0);
    expect(delay).toBeGreaterThanOrEqual(1000);
    expect(delay).toBeLessThanOrEqual(1200);
  });

  test('retry 1 → delay in [2000, 2400] ms range', () => {
    const delay = client.backoffDelayMs(1);
    expect(delay).toBeGreaterThanOrEqual(2000);
    expect(delay).toBeLessThanOrEqual(2400);
  });

  test('retry 2 → delay in [4000, 4800] ms range', () => {
    const delay = client.backoffDelayMs(2);
    expect(delay).toBeGreaterThanOrEqual(4000);
    expect(delay).toBeLessThanOrEqual(4800);
  });

  test('caps at 30 s for high retry counts', () => {
    const delay = client.backoffDelayMs(20);
    expect(delay).toBeLessThanOrEqual(30_000 * 1.2); // max + jitter
  });

  test('delay grows with retry count', () => {
    // Remove jitter effect by comparing averages across retries
    const avg = (n: number) =>
      Array.from({length: 10}, () => client.backoffDelayMs(n)).reduce(
        (a, b) => a + b,
        0,
      ) / 10;
    expect(avg(1)).toBeGreaterThan(avg(0));
    expect(avg(2)).toBeGreaterThan(avg(1));
  });
});

// ---------------------------------------------------------------------------
// Connection lifecycle
// ---------------------------------------------------------------------------

describe('WebSocketClient connection', () => {
  let client: WebSocketClient;
  const callbacks = {onRouteUpdated: jest.fn(), onConnected: jest.fn()};

  beforeEach(() => {
    jest.useFakeTimers();
    MockWebSocket.reset();
    client = new WebSocketClient();
    callbacks.onRouteUpdated.mockClear();
    callbacks.onConnected.mockClear();
  });

  afterEach(() => {
    jest.useRealTimers();
    client.disconnect();
  });

  test('connect opens a WebSocket to the correct URL', async () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    await flushTimers();
    expect(MockWebSocket.instances[0].url).toBe(
      'ws://localhost:8000/ws/driver/driver-001',
    );
  });

  test('isConnected is true after open', async () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    jest.runAllTimers();
    expect(client.isConnected).toBe(true);
  });

  test('onConnected callback fires on open', async () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    jest.runAllTimers();
    expect(callbacks.onConnected).toHaveBeenCalledTimes(1);
  });

  test('disconnect closes the socket and prevents reconnect', async () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    jest.runAllTimers();
    client.disconnect();
    expect(client.isConnected).toBe(false);
    // No reconnect timer should fire after intentional close
    jest.runAllTimers();
    expect(MockWebSocket.instances).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Message parsing
// ---------------------------------------------------------------------------

describe('WebSocketClient message handling', () => {
  let client: WebSocketClient;
  const callbacks = {onRouteUpdated: jest.fn(), onConnected: jest.fn()};

  beforeEach(() => {
    jest.useFakeTimers();
    MockWebSocket.reset();
    client = new WebSocketClient();
    callbacks.onRouteUpdated.mockClear();
  });

  afterEach(() => {
    jest.useRealTimers();
    client.disconnect();
  });

  function getSocket(): MockWebSocket {
    return MockWebSocket.instances[0];
  }

  test('route_updated message calls onRouteUpdated with stops', () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    jest.runAllTimers();

    const stops = [
      {
        stop_id: 's1',
        sequence: 1,
        location: {lat: 37.77, lng: -122.41},
        arrival_time: '09:15',
        departure_time: '09:25',
      },
    ];
    getSocket().simulateMessage(
      JSON.stringify({type: 'route_updated', reason: 'traffic_delay', optimized_stops: stops}),
    );
    expect(callbacks.onRouteUpdated).toHaveBeenCalledWith(stops);
  });

  test('ping message triggers pong response', () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    jest.runAllTimers();

    getSocket().simulateMessage(
      JSON.stringify({type: 'ping', server_time: '2030-01-01T00:00:00Z'}),
    );
    const lastMsg = JSON.parse(
      getSocket().sentMessages[getSocket().sentMessages.length - 1],
    );
    expect(lastMsg.type).toBe('pong');
    expect(lastMsg.client_time).toBeDefined();
  });

  test('invalid JSON is silently ignored', () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    jest.runAllTimers();
    expect(() => getSocket().simulateMessage('not-json{{')).not.toThrow();
    expect(callbacks.onRouteUpdated).not.toHaveBeenCalled();
  });

  test('unknown message type does not throw', () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    jest.runAllTimers();
    expect(() =>
      getSocket().simulateMessage(JSON.stringify({type: 'future_message'})),
    ).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// sendGpsUpdate
// ---------------------------------------------------------------------------

describe('WebSocketClient.sendGpsUpdate', () => {
  let client: WebSocketClient;
  const callbacks = {onRouteUpdated: jest.fn()};

  beforeEach(() => {
    jest.useFakeTimers();
    MockWebSocket.reset();
    client = new WebSocketClient();
  });

  afterEach(() => {
    jest.useRealTimers();
    client.disconnect();
  });

  test('sends gps_update message with correct fields', () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    jest.runAllTimers();

    client.sendGpsUpdate({
      lat: 37.77,
      lng: -122.41,
      timestamp: '2030-06-15T09:10:00Z',
      speed: 14,
    });

    const socket = MockWebSocket.instances[0];
    const msg = JSON.parse(socket.sentMessages[0]);
    expect(msg.type).toBe('gps_update');
    expect(msg.lat).toBe(37.77);
    expect(msg.lng).toBe(-122.41);
    expect(msg.timestamp).toBe('2030-06-15T09:10:00Z');
    expect(msg.completed_stop_id).toBeUndefined();
  });

  test('includes completed_stop_id when provided', () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    jest.runAllTimers();

    client.sendGpsUpdate(
      {lat: 37.77, lng: -122.41, timestamp: '2030-06-15T09:10:00Z', speed: 0},
      'stop-42',
    );

    const msg = JSON.parse(MockWebSocket.instances[0].sentMessages[0]);
    expect(msg.completed_stop_id).toBe('stop-42');
  });

  test('send is a no-op when not connected', () => {
    // No connect() called — should not throw
    expect(() =>
      client.sendGpsUpdate({
        lat: 0,
        lng: 0,
        timestamp: '2030-01-01T00:00:00Z',
        speed: 0,
      }),
    ).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// Reconnect logic
// ---------------------------------------------------------------------------

describe('WebSocketClient auto-reconnect', () => {
  let client: WebSocketClient;
  const callbacks = {
    onRouteUpdated: jest.fn(),
    onConnected: jest.fn(),
    onFailed: jest.fn(),
  };

  beforeEach(() => {
    jest.useFakeTimers();
    MockWebSocket.reset();
    client = new WebSocketClient();
    callbacks.onConnected.mockClear();
    callbacks.onFailed.mockClear();
  });

  afterEach(() => {
    jest.useRealTimers();
    client.disconnect();
  });

  test('reconnects after unexpected close', () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    jest.runAllTimers(); // open

    MockWebSocket.instances[0].simulateClose(1006); // abnormal close
    jest.runAllTimers(); // backoff timer fires → new socket

    expect(MockWebSocket.instances).toHaveLength(2);
  });

  test('stops reconnecting after max retries', () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);

    for (let i = 0; i <= 5; i++) {
      jest.runAllTimers();
      const last = MockWebSocket.instances[MockWebSocket.instances.length - 1];
      last.simulateClose(1006);
    }
    jest.runAllTimers();

    expect(callbacks.onFailed).toHaveBeenCalledTimes(1);
  });

  test('resets retry count after successful reconnect', () => {
    client.connect('ws://localhost:8000', 'driver-001', callbacks);
    jest.runAllTimers(); // open → retryCount=0

    // Cause one disconnect + reconnect
    MockWebSocket.instances[0].simulateClose(1006);
    jest.runAllTimers(); // retry socket opens
    jest.runAllTimers(); // new socket opens → retryCount=0 again

    // onConnected should fire twice (initial + after reconnect)
    expect(callbacks.onConnected).toHaveBeenCalledTimes(2);
  });
});
