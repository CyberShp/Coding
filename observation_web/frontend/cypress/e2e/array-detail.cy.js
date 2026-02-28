describe('Array Detail', () => {
  const testArrayId = 'test-array-001'

  beforeEach(() => {
    cy.intercept('GET', `/api/arrays/${testArrayId}/status`, { fixture: 'array-status.json' }).as('getArrayStatus')
    cy.intercept('GET', `/api/arrays/${testArrayId}/alerts*`, { fixture: 'array-alerts.json' }).as('getArrayAlerts')
    cy.intercept('GET', `/api/arrays/${testArrayId}/metrics*`, { fixture: 'array-metrics.json' }).as('getArrayMetrics')
    cy.visit(`/arrays/${testArrayId}`)
  })

  it('should display array detail page', () => {
    cy.wait('@getArrayStatus')
    cy.get('.array-detail, [class*="detail"]').should('exist')
  })

  it('should show array connection status', () => {
    cy.wait('@getArrayStatus')
    cy.get('[class*="status"], .el-tag').should('exist')
  })

  it('should display active issues if any', () => {
    cy.wait('@getArrayStatus')
    cy.get('[class*="issue"], [class*="problem"], .active-issues').should('exist')
  })

  it('should have tabs for different sections', () => {
    cy.wait('@getArrayStatus')
    cy.get('.el-tabs, [role="tablist"]').should('exist')
  })

  it('should refresh data automatically', () => {
    cy.wait('@getArrayStatus')
    cy.clock()
    cy.tick(30000)
    cy.wait('@getArrayStatus')
  })

  it('should handle manual refresh without race condition', () => {
    cy.wait('@getArrayStatus')
    // Click refresh multiple times quickly
    cy.contains('button', '刷新').click()
    cy.contains('button', '刷新').click()
    // Should not cause errors
    cy.get('.array-detail, [class*="detail"]').should('exist')
  })

  it('should show recent alerts for the array', () => {
    cy.wait('@getArrayAlerts')
    cy.contains('告警').should('exist')
  })

  it('should navigate back to arrays list', () => {
    cy.wait('@getArrayStatus')
    cy.go('back')
    cy.url().should('not.include', testArrayId)
  })
})
