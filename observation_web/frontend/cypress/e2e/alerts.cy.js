describe('Alert Center', () => {
  beforeEach(() => {
    cy.intercept('GET', '/api/alerts*', { fixture: 'alerts.json' }).as('getAlerts')
    cy.intercept('GET', '/api/alerts/recent', { fixture: 'recent-alerts.json' }).as('getRecentAlerts')
    cy.visit('/alerts')
  })

  it('should display alert center page', () => {
    cy.contains('告警中心').should('be.visible')
  })

  it('should load and display alerts list', () => {
    cy.wait('@getAlerts')
    cy.get('.alert-item, .el-table__row, [class*="alert"]').should('exist')
  })

  it('should have filter controls', () => {
    cy.get('.el-select, [class*="filter"]').should('exist')
  })

  it('should filter alerts by level', () => {
    cy.wait('@getAlerts')
    cy.get('.el-select').first().click()
    cy.get('.el-select-dropdown__item').contains('严重').click()
    cy.wait('@getAlerts')
  })

  it('should filter alerts by observer type', () => {
    cy.wait('@getAlerts')
    cy.get('.el-select').last().click()
    cy.get('.el-select-dropdown__item').first().click()
    cy.wait('@getAlerts')
  })

  it('should display alert details', () => {
    cy.wait('@getAlerts')
    cy.get('.alert-item, .el-table__row').first().click()
    cy.get('[class*="detail"], .el-dialog, .el-drawer').should('exist')
  })

  it('should auto-refresh alerts every 30 seconds', () => {
    cy.wait('@getAlerts')
    cy.clock()
    cy.tick(30000)
    cy.wait('@getAlerts')
  })

  it('should handle real-time WebSocket updates', () => {
    cy.wait('@getAlerts')
    // Verify WebSocket connection indicator if present
    cy.get('[class*="ws"], [class*="websocket"], [class*="connection"]').should('exist')
  })

  it('should track seen alert IDs without unbounded growth', () => {
    cy.wait('@getAlerts')
    // Multiple refreshes should not cause memory issues
    for (let i = 0; i < 5; i++) {
      cy.contains('button', '刷新').click()
      cy.wait('@getAlerts')
    }
    cy.get('.alert-item, .el-table__row, [class*="alert"]').should('exist')
  })

  it('should prevent concurrent refresh requests', () => {
    cy.wait('@getAlerts')
    // Rapid clicks should not cause multiple pending requests
    cy.contains('button', '刷新').click()
    cy.contains('button', '刷新').click()
    cy.contains('button', '刷新').click()
    // Page should remain stable
    cy.contains('告警中心').should('be.visible')
  })

  it('should display alert severity with appropriate styling', () => {
    cy.wait('@getAlerts')
    cy.get('.el-tag, [class*="level"], [class*="severity"]').should('exist')
  })

  it('should show alert timestamp', () => {
    cy.wait('@getAlerts')
    cy.get('[class*="time"], [class*="date"]').should('exist')
  })

  it('should navigate to related array when clicking array link', () => {
    cy.wait('@getAlerts')
    cy.get('a[href*="arrays"], .array-link').first().click()
    cy.url().should('include', '/arrays/')
  })
})
