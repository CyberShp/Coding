/**
 * alertHelpers.js — pure helpers for the multi-user Phase 3 alert UI.
 *
 * Kept framework-free so the show/hide + permission logic that drives v-if /
 * :disabled across AlertDetailDrawer / FoldedAlertList can be unit-tested
 * directly (see tests/unit/phase3.spec.js).
 */

/** Message shown when a non-creator / non-admin tries to undo an ack. */
export const UNDO_FORBIDDEN_HINT = '仅确认者或管理员可撤销'

/**
 * Whether an ack was performed by an identifiable human account.
 * System-generated acks (test-period auto-expected, legacy public acks with
 * no nickname) have no human acknowledger.
 */
export function hasHumanAcker(ack) {
  return !!(ack && ack.acked_by_nickname)
}

/**
 * canUndoAck — the single source of truth for "may this user undo this ack".
 *
 * Rules (design §三: ack 撤销仅限确认者本人或 admin):
 *   - anonymous (not logged in)                → false (write gate)
 *   - admin                                    → true  (override)
 *   - system / public ack (no human acker)     → true  (any logged-in user)
 *   - human ack                                → only the original acknowledger
 *
 * @param {object|null} ack   ack detail, expects { acked_by_nickname }
 * @param {object|null} user  current user, expects { nickname, is_admin }
 * @returns {boolean}
 */
export function canUndoAck(ack, user) {
  if (!user || !user.nickname) return false
  if (user.is_admin) return true
  if (!hasHumanAcker(ack)) return true
  return ack.acked_by_nickname === user.nickname
}

/**
 * Build a user-facing error message for a failed undo, mapping the backend's
 * 403 (English detail) to the localized permission hint.
 */
export function ackUndoErrorMessage(e, fallback = '撤销失败') {
  if (e?.response?.status === 403) return UNDO_FORBIDDEN_HINT
  return `${fallback}: ${e?.response?.data?.detail || e?.message || '未知错误'}`
}

/**
 * Whether an alert is a test-period "expected" alert (is_expected === 1).
 * -1 = 明确非预期, 0 = 未判定, 1 = 测试期预期内.
 */
export function isExpectedTestAlert(alert) {
  return alert?.is_expected === 1
}
