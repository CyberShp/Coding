import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

import { translateAlert } from '@/utils/alertTranslator'
import { useAlertFolding } from '@/composables/useAlertFolding'

describe('card_info regressions', () => {
  it('translates nested fields payload without undefined placeholders', () => {
    const result = translateAlert({
      observer_name: 'card_info',
      message: '卡件 No001 异常',
      details: {
        total_cards: 2,
        alerts: [
          {
            card: 'No001',
            board_id: 'B001',
            fields: [
              { field: 'RunningState', value: 'OFFLINE' },
              { field: 'HealthState', value: 'FAULT' },
            ],
          },
        ],
      },
    })

    expect(result.event).toContain('No001')
    expect(result.event).toContain('RunningState=OFFLINE')
    expect(result.event).toContain('HealthState=FAULT')
    expect(result.event).not.toContain('undefined=undefined')
  })

  it('folds repeated card_info alerts by nested field identity', () => {
    const alerts = ref([
      {
        observer_name: 'card_info',
        array_id: 'arr-1',
        array_name: '阵列A',
        level: 'warning',
        message: '卡件告警 1',
        timestamp: '2026-03-14T10:00:00',
        details: {
          alerts: [
            {
              card: 'No001',
              board_id: 'B001',
              fields: [{ field: 'RunningState', value: 'OFFLINE' }],
            },
          ],
        },
      },
      {
        observer_name: 'card_info',
        array_id: 'arr-1',
        array_name: '阵列A',
        level: 'warning',
        message: '卡件告警 2',
        timestamp: '2026-03-14T10:05:00',
        details: {
          alerts: [
            {
              card: 'No001',
              board_id: 'B001',
              fields: [{ field: 'RunningState', value: 'OFFLINE' }],
            },
          ],
        },
      },
    ])

    const { foldedAlerts } = useAlertFolding(alerts)

    expect(foldedAlerts.value).toHaveLength(1)
    expect(foldedAlerts.value[0].count).toBe(2)
  })

  it('keeps legacy flat card_info payload compatible', () => {
    const result = translateAlert({
      observer_name: 'card_info',
      message: '旧结构卡件异常',
      details: {
        total_cards: 1,
        alerts: [
          {
            card: 'No003',
            board_id: 'B003',
            field: 'Model',
            value: '(空)',
          },
        ],
      },
    })

    expect(result.event).toContain('No003')
    expect(result.event).toContain('Model=(空)')
  })

  it('does not fold different nested card_info fields together', () => {
    const alerts = ref([
      {
        observer_name: 'card_info',
        array_id: 'arr-1',
        array_name: '阵列A',
        level: 'warning',
        message: '卡件告警 1',
        timestamp: '2026-03-14T10:00:00',
        details: {
          alerts: [
            {
              card: 'No001',
              board_id: 'B001',
              fields: [{ field: 'RunningState', value: 'OFFLINE' }],
            },
          ],
        },
      },
      {
        observer_name: 'card_info',
        array_id: 'arr-1',
        array_name: '阵列A',
        level: 'warning',
        message: '卡件告警 2',
        timestamp: '2026-03-14T10:05:00',
        details: {
          alerts: [
            {
              card: 'No001',
              board_id: 'B001',
              fields: [{ field: 'HealthState', value: 'FAULT' }],
            },
          ],
        },
      },
    ])

    const { foldedAlerts } = useAlertFolding(alerts)

    expect(foldedAlerts.value).toHaveLength(2)
  })
})
