import { AuthProvider, useAuth } from './auth/AuthContext.jsx';
import { AppShell } from './components/AppShell.jsx';
import { ForbiddenState } from './components/ForbiddenState.jsx';
import { LoadingState } from './components/ui/StateViews.jsx';
import { useHashRoute } from './hooks/useHashRoute.js';
import { canOpen, homePage } from './lib/access.js';
import { AccountPage, RequiredPasswordChangePage } from './pages/AccountPage.jsx';
import { AdminPage } from './pages/AdminPage.jsx';
import { AssistantPage } from './pages/AssistantPage.jsx';
import { HomePage } from './pages/HomePage.jsx';
import { LoginPage } from './pages/LoginPage.jsx';
import { MyWorkPage } from './pages/MyWorkPage.jsx';
import { ReportsPage } from './pages/ReportsPage.jsx';

const PAGES = {
  'my-work': MyWorkPage,
  dashboard: HomePage,
  reports: ReportsPage,
  assistant: AssistantPage,
  admin: AdminPage,
  account: AccountPage,
};

function ProtectedApp() {
  const { status, user } = useAuth();
  const route = useHashRoute();

  if (status === 'checking') {
    return (
      <div className="gate">
        <LoadingState label="Checking your session…" />
      </div>
    );
  }
  if (status !== 'signed_in') return <LoginPage />;
  if (user.must_change_password) return <RequiredPasswordChangePage />;

  const page = route === 'home' ? homePage(user) : route;
  const Page = PAGES[page];
  return (
    <AppShell route={page}>
      {canOpen(user, page) ? <Page /> : <ForbiddenState home={homePage(user)} />}
    </AppShell>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <ProtectedApp />
    </AuthProvider>
  );
}