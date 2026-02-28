// Cypress E2E support file

// Custom commands
Cypress.Commands.add('login', () => {
  // Add login logic if needed
})

Cypress.Commands.add('waitForApi', () => {
  cy.intercept('/api/**').as('apiCall')
  cy.wait('@apiCall')
})

// Handle uncaught exceptions
Cypress.on('uncaught:exception', (err, runnable) => {
  // Returning false prevents Cypress from failing the test
  if (err.message.includes('ResizeObserver loop')) {
    return false
  }
  return true
})

// Global before each
beforeEach(() => {
  // Reset any state before each test
})
