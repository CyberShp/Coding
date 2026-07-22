/**
 * Minimal event bus for auth-related global events (mitt-style).
 *
 * Used to decouple the API layer from the UI: when a write request is
 * rejected with 401 {"detail":"login_required"}, the API interceptor emits
 * 'login-required' and App.vue opens the LoginDialog.
 */

const listeners = new Map()

export const AUTH_LOGIN_REQUIRED = 'login-required'

export function on(event, handler) {
  if (!listeners.has(event)) listeners.set(event, new Set())
  listeners.get(event).add(handler)
}

export function off(event, handler) {
  listeners.get(event)?.delete(handler)
}

export function emit(event, payload) {
  listeners.get(event)?.forEach(handler => {
    try {
      handler(payload)
    } catch (e) {
      console.error(`authEvents handler error for "${event}":`, e)
    }
  })
}

export default { on, off, emit, AUTH_LOGIN_REQUIRED }
