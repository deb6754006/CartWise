describe('api client', () => {
  const original = process.env.EXPO_PUBLIC_API_URL;

  afterEach(() => {
    if (original === undefined) delete process.env.EXPO_PUBLIC_API_URL;
    else process.env.EXPO_PUBLIC_API_URL = original;
    jest.resetModules();
  });

  it('defaults to the Android emulator host', () => {
    delete process.env.EXPO_PUBLIC_API_URL;
    jest.isolateModules(() => {
      const { API_URL, DEFAULT_API_URL } = require('../src/api/client');
      expect(DEFAULT_API_URL).toBe('http://10.0.2.2:8000');
      expect(API_URL).toBe('http://10.0.2.2:8000');
    });
  });

  it('uses EXPO_PUBLIC_API_URL when set', () => {
    process.env.EXPO_PUBLIC_API_URL = 'http://192.168.1.5:8000';
    jest.isolateModules(() => {
      const { API_URL } = require('../src/api/client');
      expect(API_URL).toBe('http://192.168.1.5:8000');
    });
  });
});
