import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DashboardPage, INITIAL_FILTERS, applyFilterChange } from './DashboardPage.jsx';
import { jsonResponse, requestsTo, stubFetch } from '../test/fetchMock.js';
import { dashboardRoutes } from '../test/dashboardRoutes.js';
import { SUMMARY, emptySummary } from '../test/dashboardFixtures.js';
import { presetRange, utcOffsetMinutes } from '../lib/dates.js';

function kpi(name) {
    return screen.getByRole('group', { name });
}

function lastDashboardQuery(fetchMock) {
    const queries = requestsTo(fetchMock, '/analytics/dashboard');
    return queries[queries.length - 1];
}

async function renderLoaded(overrides) {
    const fetchMock = stubFetch(dashboardRoutes(overrides));
    render(<DashboardPage />);
    await within(await screen.findByRole('group', { name: 'Total output' })).findByText('1,800');
    return fetchMock;
}

describe('DashboardPage — rendering', () => {
    it('shows KPI cards computed from the API summary', async () => {
        await renderLoaded();
        expect(within(kpi('Total output')).getByText('1,800')).toBeInTheDocument();
        expect(within(kpi('Target achievement')).getByText('90.0%')).toBeInTheDocument();
        expect(within(kpi('Accepted')).getByText('1,700')).toBeInTheDocument();
        expect(within(kpi('Accepted')).getByText(/First-pass yield 96\.6%/)).toBeInTheDocument();
        expect(within(kpi('Rejected')).getByText(/Rejection rate 3\.3%/)).toBeInTheDocument();
        expect(within(kpi('Defect rate')).getByText('4.5%')).toBeInTheDocument();
        expect(within(kpi('Machine downtime')).getByText('3 h 30 min')).toBeInTheDocument();
        expect(within(kpi('Open maintenance')).getByText('3')).toBeInTheDocument();
        expect(within(kpi('Open maintenance')).getByText('1 critical · 1 high priority')).toBeInTheDocument();
    });

    it('labels synthetic data clearly', async () => {
        await renderLoaded();
        expect(screen.getByRole('note')).toHaveTextContent(/12 of the records in view are synthetic sample data/);
    });

    it('renders charts, breakdowns and their accessible data tables', async () => {
        await renderLoaded();
        expect(screen.getByRole('img', { name: 'Production output and target per day' })).toBeInTheDocument();
        expect(screen.getByRole('img', { name: 'Defect rate per day' })).toBeInTheDocument();

        const defects = screen.getByRole('list', { name: 'Defective units by category' });
        expect(within(defects).getByText('SYN-DIM · Synthetic: dimensional')).toBeInTheDocument();
        expect(within(defects).getByText('11 units')).toBeInTheDocument();

        const downtime = screen.getByRole('list', { name: 'Downtime duration by machine' });
        expect(within(downtime).getByText('2 h 30 min')).toBeInTheDocument();
        expect(within(downtime).getByText('1 event')).toBeInTheDocument();

        // inside a collapsed <details>, so query hidden elements too
        const productionTable = screen.getByRole('table', { name: 'Production output and target per day', hidden: true });
        expect(within(productionTable).getByRole('rowheader', { name: 'Jan 6, 2026', hidden: true })).toBeInTheDocument();
        expect(within(productionTable).getByText('560 units')).toBeInTheDocument();
    });

    it('shows maintenance backlog and paginated operations tables', async () => {
        await renderLoaded();
        const backlog = screen.getByRole('region', { name: 'Maintenance backlog' });
        expect(within(backlog).getByText('In progress').nextSibling).toHaveTextContent('1');

        const requests = await screen.findByRole('region', { name: 'Maintenance requests' });
        expect(await within(requests).findByText('Synthetic issue 2')).toBeInTheDocument();
        expect(within(requests).getAllByText('SYN-PRS-01').length).toBeGreaterThan(0); // machine id → code
    });

    it('shows loading states while the summary is in flight', async () => {
        stubFetch(dashboardRoutes({ '/analytics/dashboard': () => new Promise(() => { }) }));
        render(<DashboardPage />);
        expect(screen.getByText('Loading production trend…')).toBeInTheDocument();
        expect(kpi('Total output')).toHaveAttribute('aria-busy', 'true');
        expect(screen.getByRole('button', { name: 'Refreshing…' })).toBeDisabled();

        // let the requests that do resolve (filter options, tables) settle inside the test
        await screen.findByRole('option', { name: 'SYN-PRS-01 · Synthetic Stamping Press 01' });
        await screen.findByRole('option', { name: 'SYN-PART-1001 · Synthetic Bracket A' });
        await screen.findByText('Showing 1–10 of 14');
        await within(screen.getByRole('region', { name: 'Maintenance requests' })).findByText('Synthetic issue 2');
    });
});

describe('DashboardPage — filters', () => {
    it('sends the browser UTC offset and no unset filters on first load', async () => {
        const fetchMock = await renderLoaded();
        const query = Object.fromEntries(requestsTo(fetchMock, '/analytics/dashboard')[0]);
        expect(query).toEqual({ utc_offset_minutes: String(utcOffsetMinutes(null)) });
    });

    it('refetches with machine, shift and data-source filters', async () => {
        const user = userEvent.setup();
        const fetchMock = await renderLoaded();

        await screen.findByRole('option', { name: 'SYN-PRS-01 · Synthetic Stamping Press 01' });
        await user.selectOptions(screen.getByLabelText('Machine'), '2');
        await waitFor(() => expect(lastDashboardQuery(fetchMock).get('machine_id')).toBe('2'));

        await user.selectOptions(screen.getByLabelText('Shift'), 'B');
        await user.selectOptions(screen.getByLabelText('Data source'), 'manual');
        await waitFor(() => {
            const query = lastDashboardQuery(fetchMock);
            expect(query.get('shift')).toBe('B');
            expect(query.get('data_source')).toBe('manual');
            expect(query.get('machine_id')).toBe('2');
        });

        // the operations tables follow the machine and data-source filters too
        await waitFor(() => {
            const downtime = requestsTo(fetchMock, '/downtime-events');
            expect(downtime[downtime.length - 1].get('machine_id')).toBe('2');
            expect(downtime[downtime.length - 1].get('data_source')).toBe('manual');
        });
    });

    it('applies date presets as inclusive calendar ranges', async () => {
        const user = userEvent.setup();
        const fetchMock = await renderLoaded();
        await user.selectOptions(screen.getByLabelText('Period'), '7d');
        const expected = presetRange('7d', new Date());
        await waitFor(() => {
            const query = lastDashboardQuery(fetchMock);
            expect(query.get('date_from')).toBe(expected.from);
            expect(query.get('date_to')).toBe(expected.to);
        });
        expect(screen.getByLabelText('From')).toHaveValue(expected.from);
    });

    it('validates a custom range locally and does not call the API with it', async () => {
        const fetchMock = await renderLoaded();
        fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-01-10' } });
        fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-01-05' } });

        expect(await screen.findByRole('alert')).toHaveTextContent('Start date must be on or before the end date.');
        expect(screen.getByLabelText('To')).toHaveAttribute('aria-invalid', 'true');
        expect(screen.getByLabelText('Period')).toHaveValue('custom');
        expect(requestsTo(fetchMock, '/analytics/dashboard').some((q) => q.get('date_to') === '2026-01-05')).toBe(false);
        expect(screen.queryByRole('group', { name: 'Total output' })).not.toBeInTheDocument();
    });

    it('turns a custom range into local-midnight UTC instants for the downtime list', async () => {
        const fetchMock = await renderLoaded();
        fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-01-05' } });
        fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-01-07' } });
        await waitFor(() => {
            const downtime = requestsTo(fetchMock, '/downtime-events');
            const query = downtime[downtime.length - 1];
            expect(query.get('started_from')).toBe(new Date(2026, 0, 5).toISOString());
            expect(query.get('started_to')).toBe(new Date(new Date(2026, 0, 8).getTime() - 1).toISOString());
        });
        expect(lastDashboardQuery(fetchMock).get('utc_offset_minutes')).toBe(String(utcOffsetMinutes('2026-01-05')));
    });

    it('resets every filter', async () => {
        const user = userEvent.setup();
        const fetchMock = await renderLoaded();
        await user.selectOptions(screen.getByLabelText('Shift'), 'A');
        await user.click(screen.getByRole('button', { name: 'Reset filters' }));
        await waitFor(() => expect(lastDashboardQuery(fetchMock).get('shift')).toBeNull());
        expect(screen.getByLabelText('Shift')).toHaveValue('');
    });

    it('keeps presets and explicit dates consistent', () => {
        const today = new Date(2026, 0, 18);
        expect(applyFilterChange(INITIAL_FILTERS, { preset: '7d' }, today)).toMatchObject({
            preset: '7d', dateFrom: '2026-01-12', dateTo: '2026-01-18',
        });
        const custom = applyFilterChange(INITIAL_FILTERS, { preset: 'custom', dateFrom: '2026-01-02' }, today);
        expect(custom).toMatchObject({ preset: 'custom', dateFrom: '2026-01-02', dateTo: '' });
    });
});

describe('DashboardPage — pagination', () => {
    it('pages through downtime events using the API envelope', async () => {
        const user = userEvent.setup();
        const fetchMock = await renderLoaded();
        const nav = await screen.findByRole('navigation', { name: 'Downtime events pages' });
        expect(nav).toHaveTextContent('Showing 1–10 of 14');
        expect(within(nav).getByRole('button', { name: 'Previous' })).toBeDisabled();

        await user.click(within(nav).getByRole('button', { name: 'Next' }));
        expect(await screen.findByText('Showing 11–14 of 14')).toBeInTheDocument();
        const offsets = requestsTo(fetchMock, '/downtime-events').map((q) => q.get('offset'));
        expect(offsets).toContain('10');
        expect(within(screen.getByRole('navigation', { name: 'Downtime events pages' })).getByRole('button', { name: 'Next' })).toBeDisabled();
    });
});

describe('DashboardPage — empty and failure states', () => {
    it('shows an empty state and offers the period that has data', async () => {
        const user = userEvent.setup();
        const fetchMock = stubFetch(
            dashboardRoutes({
                '/analytics/dashboard': (url) =>
                    jsonResponse(
                        url.searchParams.get('date_from')
                            ? SUMMARY
                            : emptySummary({ data_range: { first_date: '2026-01-05', last_date: '2026-01-07' } }),
                    ),
            }),
        );
        render(<DashboardPage />);
        const empty = await screen.findByRole('region', { name: 'No manufacturing data for these filters' });
        expect(empty).toHaveTextContent('Data is available from Jan 5, 2026 – Jan 7, 2026.');
        expect(screen.queryByRole('group', { name: 'Total output' })).not.toBeInTheDocument();

        await user.click(within(empty).getByRole('button', { name: 'Show that period' }));
        await waitFor(() => {
            const query = lastDashboardQuery(fetchMock);
            expect(query.get('date_from')).toBe('2026-01-05');
            expect(query.get('date_to')).toBe('2026-01-07');
        });
        expect(await within(await screen.findByRole('group', { name: 'Total output' })).findByText('1,800')).toBeInTheDocument();
    });

    it('shows an empty state without fake figures when the database is empty', async () => {
        stubFetch(dashboardRoutes({ '/analytics/dashboard': jsonResponse(emptySummary()) }));
        render(<DashboardPage />);
        const empty = await screen.findByRole('region', { name: 'No manufacturing data for these filters' });
        expect(empty).toHaveTextContent('Load production data through the API');
        expect(screen.queryByRole('note')).not.toBeInTheDocument();
    });

    it('shows server failures with the request id and recovers on retry', async () => {
        const user = userEvent.setup();
        const routes = dashboardRoutes({
            '/analytics/dashboard': jsonResponse(
                { error: { code: 'internal_error', message: 'Internal server error', request_id: 'req-500' } },
                { status: 500 },
            ),
        });
        stubFetch(routes);
        render(<DashboardPage />);

        const alert = await screen.findByRole('alert');
        expect(alert).toHaveTextContent('The server could not complete the request.');
        expect(alert).toHaveTextContent('request id req-500');
        expect(screen.queryByRole('group', { name: 'Total output' })).not.toBeInTheDocument();

        routes['/analytics/dashboard'] = jsonResponse(SUMMARY);
        await user.click(within(alert).getByRole('button', { name: 'Try again' }));
        expect(await within(await screen.findByRole('group', { name: 'Total output' })).findByText('1,800')).toBeInTheDocument();
    });

    it('explains backend validation errors', async () => {
        stubFetch(
            dashboardRoutes({
                '/analytics/dashboard': jsonResponse(
                    { error: { code: 'invalid_date_range', message: 'date_from must be on or before date_to', request_id: 'r422' } },
                    { status: 422 },
                ),
            }),
        );
        render(<DashboardPage />);
        const alert = await screen.findByRole('alert');
        expect(alert).toHaveTextContent('The filters were rejected.');
        expect(alert).toHaveTextContent('date_from must be on or before date_to');
    });

    it('reports an unreachable API', async () => {
        stubFetch(dashboardRoutes({ '/analytics/dashboard': new TypeError('Failed to fetch') }));
        render(<DashboardPage />);
        expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the FoundryOS API');
    });

    it('keeps working when filter options cannot be loaded', async () => {
        stubFetch(dashboardRoutes({ '/machines': new TypeError('Failed to fetch') }));
        render(<DashboardPage />);
        await within(await screen.findByRole('group', { name: 'Total output' })).findByText('1,800');
        expect(await screen.findByText(/Some filter options could not be loaded/)).toBeInTheDocument();
        expect(screen.getByLabelText('Machine')).toBeDisabled();
    });
});