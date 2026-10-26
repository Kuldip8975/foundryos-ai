import { useState } from 'react';
import { fetchDowntimeEvents, fetchMaintenanceRequests } from '../../api/manufacturing.js';
import { localDayEndISO, localDayStartISO } from '../../lib/dates.js';
import { formatDateTime, formatDuration } from '../../lib/format.js';
import { StatusBadge } from '../StatusBadge.jsx';
import { InlineSelect, PagedListCard } from './PagedListCard.jsx';

const DOWNTIME_STATUSES = [
  { value: '', label: 'All' },
  { value: 'ongoing', label: 'Ongoing' },
  { value: 'resolved', label: 'Resolved' },
];

const MAINTENANCE_STATUSES = [
  { value: '', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'closed', label: 'Closed' },
  { value: 'cancelled', label: 'Cancelled' },
];

const PRIORITIES = [
  { value: '', label: 'All' },
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
];

/**
 * scope: { dateFrom, dateTo, machineId, dataSource, refreshToken }
 * machineLabel(id) → display name for a machine id
 */
export function DowntimeEventsTable({ scope, machineLabel }) {
  const [status, setStatus] = useState('');
  const params = {
    started_from: scope.dateFrom ? localDayStartISO(scope.dateFrom) : null,
    started_to: scope.dateTo ? localDayEndISO(scope.dateTo) : null,
    machine_id: scope.machineId ? Number(scope.machineId) : null,
    status: status || null,
    data_source: scope.dataSource || null,
  };
  return (
    <PagedListCard
      title="Downtime events"
      subtitle="Events that started in the selected period, newest first. Times in your local time zone."
      actions={<InlineSelect label="Status" value={status} onChange={setStatus} options={DOWNTIME_STATUSES} />}
      scopeKey={JSON.stringify([params, scope.refreshToken])}
      fetchPage={(page, options) => fetchDowntimeEvents({ ...params, ...page }, options)}
      caption="Machine downtime events"
      emptyText="No downtime events started in this period."
      columns={[
        { key: 'machine', header: 'Machine', render: (row) => machineLabel(row.machine_id) },
        { key: 'started_at', header: 'Started', render: (row) => formatDateTime(row.started_at) },
        { key: 'ended_at', header: 'Ended', render: (row) => formatDateTime(row.ended_at) },
        {
          key: 'duration',
          header: 'Duration',
          numeric: true,
          render: (row) => (row.duration_seconds == null ? 'Ongoing' : formatDuration(row.duration_seconds)),
        },
        { key: 'status', header: 'Status', render: (row) => <StatusBadge status={row.status} /> },
        { key: 'reason', header: 'Reason' },
      ]}
    />
  );
}

export function MaintenanceRequestsTable({ scope, machineLabel }) {
  const [status, setStatus] = useState('');
  const [priority, setPriority] = useState('');
  const params = {
    machine_id: scope.machineId ? Number(scope.machineId) : null,
    status: status || null,
    priority: priority || null,
    data_source: scope.dataSource || null,
  };
  return (
    <PagedListCard
      title="Maintenance requests"
      subtitle="All requests for the machines in scope, newest first (not date-filtered)."
      actions={
        <>
          <InlineSelect label="Status" value={status} onChange={setStatus} options={MAINTENANCE_STATUSES} />
          <InlineSelect label="Priority" value={priority} onChange={setPriority} options={PRIORITIES} />
        </>
      }
      scopeKey={JSON.stringify([params, scope.refreshToken])}
      fetchPage={(page, options) => fetchMaintenanceRequests({ ...params, ...page }, options)}
      caption="Maintenance requests"
      emptyText="No maintenance requests match these filters."
      columns={[
        { key: 'machine', header: 'Machine', render: (row) => machineLabel(row.machine_id) },
        { key: 'created_at', header: 'Raised', render: (row) => formatDateTime(row.created_at) },
        { key: 'priority', header: 'Priority', render: (row) => <StatusBadge status={`priority_${row.priority}`} /> },
        { key: 'status', header: 'Status', render: (row) => <StatusBadge status={`request_${row.status}`} /> },
        { key: 'issue_description', header: 'Issue' },
        { key: 'resolved_at', header: 'Resolved', render: (row) => formatDateTime(row.resolved_at) },
      ]}
    />
  );
}