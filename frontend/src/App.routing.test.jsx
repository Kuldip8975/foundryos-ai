import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import App from './App.jsx';
import { routeFromHash } from './hooks/useHashRoute.js';
import { canOpen, homePage, navItems } from './lib/access.js';
import { jsonResponse, stubFetch } from './test/fetchMock.js';
import { dashboardRoutes } from './test/dashboardRoutes.js';
import { page } from './test/dashboardFixtures.js';
import { currentUser, startSession } from './test/authFixtures.js';

const HEALTH = {
  '/health/live': jsonResponse({ status: 'alive', service: 'FoundryOS AI', version: '0.1.0', environment: 'test' }),
  '/health/ready': jsonResponse({ status: 'ready', checks: [] }),
  '/shift-reports': jsonResponse(page([])),
  '/production-records': jsonResponse(page([])),
};

function signedInAs(role, overrides = {}) {
  startSession();
  return dashboardRoutes({ ...HEALTH, '/auth/me': jsonResponse(currentUser(role)), ...overrides });
}

function mainNav() {
  return screen.getByRole('navigation', { name: 'Main' });
}

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  window.location.hash = '';
});

describe('routes and access rules', () => {
  it('maps hashes to pages', () => {
    expect(routeFromHash('#/reports')).toBe('reports');
    expect(routeFromHash('#/assistant')).toBe('assistant');
    expect(routeFromHash('#/my-work')).toBe('my-work');
    expect(routeFromHash('#/admin')).toBe('admin');
    expect(routeFromHash('#/dashboard')).toBe('dashboard');
    expect(routeFromHash('')).toBe('home');
    expect(routeFromHash('#/')).toBe('home');
    expect(routeFromHash('#/unknown')).toBe('home');
  });

  it('gives each role only its own pages', () => {
    const pages = (role) => navItems(currentUser(role)).map((item) => item.page);
    expect(pages('operator')).toEqual(['my-work', 'assistant']);
    expect(pages('supervisor')).toEqual(['dashboard', 'reports', 'assistant']);
    expect(pages('production_manager')).toEqual(['dashboard', 'reports', 'assistant']);
    expect(pages('admin')).toEqual(['admin']);
    expect(homePage(currentUser('operator'))).toBe('my-work');
    expect(homePage(currentUser('admin'))).toBe('admin');
    expect(canOpen(currentUser('admin'), 'dashboard')).toBe(false);
    expect(canOpen(currentUser('admin'), 'account')).toBe(true);
    // A home the person may not open falls back to the first page they may.
    expect(homePage(currentUser('production_manager', { home: 'admin' }))).toBe('dashboard');
  });
});

describe('navigation', () => {
  it('opens the supervisor dashboard by default and marks it current', async () => {
    stubFetch(signedInAs('supervisor'));
    render(<App />);
    expect(await screen.findByRole('heading', { level: 2, name: 'Manufacturing dashboard' })).toBeInTheDocument();
    expect(within(mainNav()).getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page');
    await screen.findByText('Connected');
  });

  it('switches to the shift reports page when the hash changes', async () => {
    stubFetch(signedInAs('production_manager'));
    window.location.hash = '#/reports';
    render(<App />);
    expect(await screen.findByRole('heading', { level: 2, name: 'AI shift reports' })).toBeInTheDocument();
    expect(within(mainNav()).getByRole('link', { name: 'Shift reports' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('heading', { name: 'Manufacturing dashboard' })).not.toBeInTheDocument();
  });

  it('opens an operator on their machines and hides plant-wide pages', async () => {
    stubFetch(signedInAs('operator'));
    render(<App />);
    expect(await screen.findByRole('heading', { level: 2, name: 'My machines' })).toBeInTheDocument();
    expect(within(mainNav()).queryByRole('link', { name: 'Dashboard' })).not.toBeInTheDocument();
    expect(within(mainNav()).queryByRole('link', { name: 'Users & access' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Olga Operator/ })).toHaveTextContent('Operator');
  });

  it('explains when a page is not part of the role', async () => {
    stubFetch(signedInAs('operator'));
    window.location.hash = '#/dashboard';
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'This page is not part of your role' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to My machines' })).toHaveAttribute('href', '#/my-work');
    expect(screen.queryByRole('heading', { name: 'Manufacturing dashboard' })).not.toBeInTheDocument();
  });
});