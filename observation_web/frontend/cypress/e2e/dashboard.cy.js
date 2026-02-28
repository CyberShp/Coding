describe('Dashboard', () => {
  beforeEach(() => {
    cy.intercept('GET', '/api/arrays', { fixture: 'arrays.json' }).as('getArrays')
    cy.intercept('GET', '/api/alerts/recent', { fixture: 'recent-alerts.json' }).as('getRecentAlerts')
    cy.intercept('GET', '/api/alerts/summary*', { fixture: 'alert-summary.json' }).as('getAlertSummary')
    cy.intercept('GET', '/api/alerts/stats*', { fixture: 'alert-stats.json' }).as('getAlertStats')
    cy.visit('/')
  })

  it('should display the dashboard page', () => {
    cy.contains('仪表盘').should('be.visible')
  })

  it('should display stats cards', () => {
    cy.wait('@getArrays')
    cy.get('.stat-card').should('have.length.at.least', 4)
  })

  it('should have a refresh button', () => {
    cy.contains('button', '刷新').should('be.visible')
  })

  it('should refresh data when clicking refresh button', () => {
    cy.wait('@getArrays')
    cy.contains('button', '刷新').click()
    cy.wait('@getArrays')
  })

  it('should navigate to arrays page when clicking total arrays card', () => {
    cy.get('.stat-card').first().click()
    cy.url().should('include', '/arrays')
  })

  it('should navigate to alerts page when clicking alerts card', () => {
    cy.get('.stat-card').contains('告警').click()
    cy.url().should('include', '/alerts')
  })

  it('should display array list', () => {
    cy.wait('@getArrays')
    cy.get('.array-card, .array-item, [class*="array"]').should('exist')
  })

  it('should auto-refresh data', () => {
    cy.wait('@getArrays')
    // Wait for auto-refresh (30 seconds)
    cy.clock()
    cy.tick(30000)
    cy.wait('@getArrays')
  })
})
