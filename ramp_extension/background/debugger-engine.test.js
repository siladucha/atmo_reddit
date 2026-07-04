import { describe, it, expect, vi, beforeEach } from 'vitest';
import { trustedClick } from './debugger-engine.js';

// Mock chrome APIs
const mockChrome = {
  tabs: {
    sendMessage: vi.fn(),
  },
  debugger: {
    attach: vi.fn(),
    sendCommand: vi.fn(),
    detach: vi.fn(),
  },
};

// Install global chrome mock
globalThis.chrome = mockChrome;

describe('debugger-engine: trustedClick', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockChrome.debugger.attach.mockResolvedValue(undefined);
    mockChrome.debugger.sendCommand.mockResolvedValue(undefined);
    mockChrome.debugger.detach.mockResolvedValue(undefined);
  });

  it('performs full attach-mousePressed-mouseReleased-detach flow', async () => {
    mockChrome.tabs.sendMessage.mockResolvedValue({
      x: 100, y: 200, width: 50, height: 30,
    });

    await trustedClick(42, '.trigger-button');

    // Sends GET_ELEMENT_COORDS message
    expect(mockChrome.tabs.sendMessage).toHaveBeenCalledWith(42, {
      type: 'GET_ELEMENT_COORDS',
      selector: '.trigger-button',
      shadowSelector: null,
    });

    // Attaches debugger with version 1.3
    expect(mockChrome.debugger.attach).toHaveBeenCalledWith({ tabId: 42 }, '1.3');

    // Dispatches mousePressed at center (125, 215)
    expect(mockChrome.debugger.sendCommand).toHaveBeenCalledWith(
      { tabId: 42 },
      'Input.dispatchMouseEvent',
      { type: 'mousePressed', x: 125, y: 215, button: 'left', clickCount: 1 },
    );

    // Dispatches mouseReleased at center (125, 215)
    expect(mockChrome.debugger.sendCommand).toHaveBeenCalledWith(
      { tabId: 42 },
      'Input.dispatchMouseEvent',
      { type: 'mouseReleased', x: 125, y: 215, button: 'left', clickCount: 1 },
    );

    // Detaches debugger
    expect(mockChrome.debugger.detach).toHaveBeenCalledWith({ tabId: 42 });
  });

  it('passes shadowSelector to content script message', async () => {
    mockChrome.tabs.sendMessage.mockResolvedValue({
      x: 10, y: 20, width: 100, height: 40,
    });

    await trustedClick(7, 'faceplate-textarea-input', '#innerTextArea');

    expect(mockChrome.tabs.sendMessage).toHaveBeenCalledWith(7, {
      type: 'GET_ELEMENT_COORDS',
      selector: 'faceplate-textarea-input',
      shadowSelector: '#innerTextArea',
    });
  });

  it('throws "Element not found" when coords are null', async () => {
    mockChrome.tabs.sendMessage.mockResolvedValue(null);

    await expect(trustedClick(1, '.missing-element'))
      .rejects.toThrow('Element not found for click');

    // Should NOT attempt to attach debugger
    expect(mockChrome.debugger.attach).not.toHaveBeenCalled();
  });

  it('throws "Element not visible" when width is 0', async () => {
    mockChrome.tabs.sendMessage.mockResolvedValue({
      x: 50, y: 50, width: 0, height: 30,
    });

    await expect(trustedClick(1, '.hidden-element'))
      .rejects.toThrow('Element not visible for click');

    expect(mockChrome.debugger.attach).not.toHaveBeenCalled();
  });

  it('throws "Element not visible" when height is 0', async () => {
    mockChrome.tabs.sendMessage.mockResolvedValue({
      x: 50, y: 50, width: 100, height: 0,
    });

    await expect(trustedClick(1, '.collapsed'))
      .rejects.toThrow('Element not visible for click');

    expect(mockChrome.debugger.attach).not.toHaveBeenCalled();
  });

  it('detaches debugger on attach failure', async () => {
    mockChrome.tabs.sendMessage.mockResolvedValue({
      x: 10, y: 10, width: 50, height: 50,
    });
    mockChrome.debugger.attach.mockRejectedValue(new Error('Cannot attach'));

    await expect(trustedClick(1, '.btn'))
      .rejects.toThrow('Cannot attach');

    // Attach failed so detach cleanup should NOT be called (attached=false)
    expect(mockChrome.debugger.detach).not.toHaveBeenCalled();
  });

  it('detaches debugger on sendCommand failure (cleanup)', async () => {
    mockChrome.tabs.sendMessage.mockResolvedValue({
      x: 0, y: 0, width: 80, height: 40,
    });
    mockChrome.debugger.sendCommand.mockRejectedValueOnce(
      new Error('Protocol error'),
    );

    await expect(trustedClick(5, '.btn'))
      .rejects.toThrow('Protocol error');

    // Debugger was attached, so cleanup detach must happen
    expect(mockChrome.debugger.detach).toHaveBeenCalledWith({ tabId: 5 });
  });

  it('still throws original error when cleanup detach also fails', async () => {
    mockChrome.tabs.sendMessage.mockResolvedValue({
      x: 0, y: 0, width: 60, height: 20,
    });
    mockChrome.debugger.sendCommand.mockRejectedValueOnce(
      new Error('Dispatch failed'),
    );
    mockChrome.debugger.detach.mockRejectedValueOnce(
      new Error('Detach also failed'),
    );

    // Should throw the original error, not the detach error
    await expect(trustedClick(3, '.btn'))
      .rejects.toThrow('Dispatch failed');
  });

  it('calculates correct center coordinates', async () => {
    mockChrome.tabs.sendMessage.mockResolvedValue({
      x: 0, y: 0, width: 200, height: 100,
    });

    await trustedClick(1, '.large-button');

    // Center should be (100, 50)
    expect(mockChrome.debugger.sendCommand).toHaveBeenCalledWith(
      { tabId: 1 },
      'Input.dispatchMouseEvent',
      expect.objectContaining({ x: 100, y: 50 }),
    );
  });
});
