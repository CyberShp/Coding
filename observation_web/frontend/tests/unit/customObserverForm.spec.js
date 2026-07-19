import { describe, expect, it } from 'vitest'

import {
  createObserverForm,
  deploymentState,
  formToTemplatePayload,
  generatedTemplateToForm,
} from '@/components/admin/customObserverForm'


describe('custom observer studio form', () => {
  it('keeps generated extraction strategy losslessly when saving', () => {
    const form = generatedTemplateToForm({
      name: 'port_temperature',
      command: 'anytest sfpallinfo',
      strategy: 'pipe',
      strategy_config: {
        steps: [{ grep: 'Temperature' }, { regex: '(\\d+)' }],
      },
      match_condition: 'gt',
      match_threshold: '70',
    }, '监控光模块温度')

    const payload = formToTemplatePayload(form)

    expect(payload.match_type).toBe('pipe')
    expect(JSON.parse(payload.match_expression)).toEqual({
      steps: [{ grep: 'Temperature' }, { regex: '(\\d+)' }],
    })
    expect(payload.description).toBe('监控光模块温度')
  })

  it('separates audience visibility from deployment targets', () => {
    const form = createObserverForm({ visibility: 'private', team_scope: 'qa-a' })
    const payload = formToTemplatePayload(form)

    expect(payload.visibility).toBe('private')
    expect(payload.team_scope).toBe('qa-a')
    expect(payload).not.toHaveProperty('target_ids')
  })

  it('migrates a legacy regex template to the v2 lines strategy', () => {
    const form = createObserverForm({
      match_type: 'regex',
      match_expression: '([0-9.]+)',
    })

    expect(form.strategy).toBe('lines')
    expect(form.strategy_config).toEqual({ pattern: '([0-9.]+)', mode: 'first' })
    expect(JSON.parse(formToTemplatePayload(form).match_expression)).toEqual(form.strategy_config)
  })

  it('does not call an unconfirmed deployment successful', () => {
    expect(deploymentState({ status: 'active' }).label).toBe('已加载')
    expect(deploymentState({ status: 'degraded' }).label).toBe('未确认')
    expect(deploymentState({ status: 'pending' }).label).toBe('待下发')
    expect(deploymentState({ status: 'removed' }).label).toBe('已移除')
  })
})
