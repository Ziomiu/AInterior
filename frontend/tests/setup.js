import { afterEach } from 'vitest';

class LocalStorageMock {
  #store = {};

  getItem(key) {
    return Object.prototype.hasOwnProperty.call(this.#store, key) ? this.#store[key] : null;
  }

  setItem(key, value) {
    this.#store[key] = String(value);
  }

  removeItem(key) {
    delete this.#store[key];
  }

  clear() {
    this.#store = {};
  }
}

Object.defineProperty(globalThis, 'localStorage', {
  value: new LocalStorageMock(),
  writable: true,
  configurable: true,
});

afterEach(() => {
  localStorage.clear();
});
