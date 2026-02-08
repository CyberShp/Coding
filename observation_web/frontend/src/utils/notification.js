/**
 * 桌面通知和声音工具
 *
 * - 桌面通知：使用 Notification API
 * - 提示音：使用 Web Audio API 生成短促警报音
 */

let _soundEnabled = false

/**
 * 请求桌面通知权限
 */
export async function requestNotificationPermission() {
  if (!('Notification' in window)) return false
  if (Notification.permission === 'granted') return true
  if (Notification.permission === 'denied') return false
  const result = await Notification.requestPermission()
  return result === 'granted'
}

/**
 * 发送桌面通知
 */
export function sendDesktopNotification(title, body, options = {}) {
  if (!('Notification' in window)) return
  if (Notification.permission !== 'granted') return

  try {
    const n = new Notification(title, {
      body,
      icon: '/favicon.ico',
      tag: options.tag || 'critical-alert',
      renotify: true,
      ...options,
    })
    // Auto close after 8 seconds
    setTimeout(() => n.close(), 8000)
    return n
  } catch (e) {
    console.warn('Notification failed:', e)
  }
}

/**
 * 播放短促警报提示音 (Web Audio API)
 */
export function playAlertSound() {
  if (!_soundEnabled) return
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.type = 'sine'
    osc.frequency.setValueAtTime(880, ctx.currentTime) // A5
    gain.gain.setValueAtTime(0.3, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3)
    osc.start(ctx.currentTime)
    osc.stop(ctx.currentTime + 0.3)
    // Double beep
    setTimeout(() => {
      try {
        const osc2 = ctx.createOscillator()
        const gain2 = ctx.createGain()
        osc2.connect(gain2)
        gain2.connect(ctx.destination)
        osc2.type = 'sine'
        osc2.frequency.setValueAtTime(1100, ctx.currentTime)
        gain2.gain.setValueAtTime(0.3, ctx.currentTime)
        gain2.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3)
        osc2.start(ctx.currentTime)
        osc2.stop(ctx.currentTime + 0.3)
      } catch (_) {}
    }, 200)
  } catch (e) {
    console.warn('Audio playback failed:', e)
  }
}

/**
 * 启用/禁用提示音
 */
export function setSoundEnabled(enabled) {
  _soundEnabled = enabled
}

export function isSoundEnabled() {
  return _soundEnabled
}
