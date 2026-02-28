describe('Performance Monitor', () => {
  const testArrayId = 'test-array-001'

  beforeEach(() => {
    cy.intercept('GET', `/api/arrays/${testArrayId}/metrics*`, { fixture: 'metrics.json' }).as('getMetrics')
    cy.intercept('GET', `/api/arrays/${testArrayId}/status`, { fixture: 'array-status.json' }).as('getArrayStatus')
    cy.visit(`/arrays/${testArrayId}/performance`)
  })

  it('should display performance monitor page', () => {
    cy.contains('性能监控').should('be.visible')
  })

  it('should show CPU utilization chart', () => {
    cy.wait('@getMetrics')
    cy.contains('CPU').should('be.visible')
    cy.get('canvas, [class*="chart"], .echarts').should('exist')
  })

  it('should show memory utilization chart', () => {
    cy.wait('@getMetrics')
    cy.contains('内存').should('be.visible')
    cy.get('canvas, [class*="chart"], .echarts').should('have.length.at.least', 1)
  })

  it('should have auto-refresh toggle', () => {
    cy.get('[class*="switch"], .el-switch').should('exist')
  })

  it('should enable auto-refresh by default', () => {
    cy.get('.el-switch.is-checked, [class*="switch"][aria-checked="true"]').should('exist')
  })

  it('should toggle auto-refresh', () => {
    cy.get('[class*="switch"], .el-switch').click()
    cy.get('[class*="switch"], .el-switch').should('not.have.class', 'is-checked')
  })

  it('should display helpful message when no data', () => {
    cy.intercept('GET', `/api/arrays/${testArrayId}/metrics*`, { body: [] }).as('getEmptyMetrics')
    cy.visit(`/arrays/${testArrayId}/performance`)
    cy.wait('@getEmptyMetrics')
    cy.contains('暂无').should('be.visible')
    cy.contains('Agent').should('be.visible')
  })

  it('should auto-refresh metrics data', () => {
    cy.wait('@getMetrics')
    cy.clock()
    cy.tick(10000) // Metrics refresh interval
    cy.wait('@getMetrics')
  })

  it('should display latest metrics values', () => {
    cy.wait('@getMetrics')
    cy.get('[class*="metric"], [class*="value"], .latest-metrics').should('exist')
  })

  it('should show CPU status indicator', () => {
    cy.wait('@getMetrics')
    cy.get('[class*="status"], .el-tag, [class*="cpu"]').should('exist')
  })

  it('should handle time range selection if available', () => {
    cy.wait('@getMetrics')
    cy.get('.el-select, [class*="range"]').then($el => {
      if ($el.length > 0) {
        cy.wrap($el).first().click()
        cy.get('.el-select-dropdown__item').first().click()
        cy.wait('@getMetrics')
      }
    })
  })

  it('should clear timers on unmount', () => {
    cy.wait('@getMetrics')
    cy.visit('/')
    // Should not have memory leaks from abandoned timers
    cy.contains('仪表盘').should('be.visible')
  })

  it('should handle rapid navigation without errors', () => {
    cy.wait('@getMetrics')
    cy.visit('/')
    cy.visit(`/arrays/${testArrayId}/performance`)
    cy.wait('@getMetrics')
    cy.visit('/')
    // Page should remain stable
    cy.contains('仪表盘').should('be.visible')
  })
})
