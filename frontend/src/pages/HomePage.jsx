import { BackendStatusPanel } from '../components/BackendStatusPanel.jsx';
import { useBackendStatus } from '../hooks/useBackendStatus.js';
import { DashboardPage } from './DashboardPage.jsx';

/**
 * Landing page: the manufacturing dashboard (Module 2) followed by the live
 * backend connectivity panel (Module 0). Every figure comes from the API.
 */
export function HomePage() {
  const status = useBackendStatus();

  return (
    <>
      <DashboardPage />
      <div className="no-print">
        <BackendStatusPanel status={status} />
      </div>
    </>
  );
}