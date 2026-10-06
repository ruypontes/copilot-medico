import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  SESSION_EXPIRED_MESSAGE,
  clearSession,
  createPatient,
  getPatients,
  getStoredSession,
  onSessionChange,
  storeSession,
} from './api';
import Login from './components/Login.jsx';
import Layout from './components/Layout.jsx';
import Dashboard from './components/Dashboard.jsx';
import PatientsPage from './components/PatientsPage.jsx';
import PlaceholderPage from './components/PlaceholderPage.jsx';
import AdminDoctorsPage from './components/AdminDoctorsPage.jsx';

const views = {
  dashboard: { title: 'Copilot Médico' },
  medicos: { title: 'Médicos' },
  pacientes: { title: 'Pacientes' },
  agendamentos: { title: 'Agenda' },
  analise: { title: 'Consulta' },
  atendimentos: { title: 'Atendimentos' },
  relatorios: { title: 'Histórico' },
  configuracoes: { title: 'Ajustes' },
};

function App() {
  const storedSession = useMemo(() => getStoredSession(), []);
  const [session, setSession] = useState(storedSession);
  const [activeView, setActiveView] = useState('dashboard');
  const [patients, setPatients] = useState([]);
  const [patientsState, setPatientsState] = useState({ loading: false, error: '' });
  const [loginNotice, setLoginNotice] = useState('');

  const authenticated = Boolean(session.token);

  const loadPatients = useCallback(async () => {
    if (!session.token) return;

    setPatientsState({ loading: true, error: '' });
    try {
      const data = await getPatients(session.token);
      const normalized = (data.patients || []).map((patient) => ({
        id: patient.id,
        name: patient.name || patient.nome || `Paciente ${String(patient.id).slice(0, 8)}`,
      }));
      setPatients(normalized);
      setPatientsState({ loading: false, error: '' });
    } catch (error) {
      setPatientsState({ loading: false, error: error.message });
    }
  }, [session.token]);

  useEffect(() => {
    loadPatients();
  }, [loadPatients]);

  // Token renovado atualiza a sessão; sessão expirada (401 sem renovação) volta ao login.
  useEffect(
    () =>
      onSessionChange((nextSession) => {
        if (nextSession) {
          setSession(nextSession);
          return;
        }
        setSession({ token: null, user: null, profile: null });
        setPatients([]);
        setLoginNotice(SESSION_EXPIRED_MESSAGE);
      }),
    []
  );

  function handleLoginSuccess(nextSession) {
    storeSession(nextSession);
    setLoginNotice('');
    setSession(nextSession);
    setActiveView(nextSession.profile?.name === 'administrador' ? 'medicos' : 'dashboard');
  }

  function handleLogout() {
    clearSession();
    setLoginNotice('');
    setSession({ token: null, user: null, profile: null });
    setPatients([]);
  }

  async function handleCreatePatient(patient) {
    const payload = { name: patient.name.trim() };
    await createPatient(session.token, payload);
    await loadPatients();
  }

  if (!authenticated) {
    return <Login notice={loginNotice} onLoginSuccess={handleLoginSuccess} />;
  }

  const pageTitle = views[activeView]?.title || 'Dashboard';

  return (
    <Layout
      activeView={activeView}
      onViewChange={setActiveView}
      onLogout={handleLogout}
      user={session.user}
      profile={session.profile}
      pageTitle={pageTitle}
    >
      {activeView === 'dashboard' && (
        <Dashboard
          patients={patients}
          patientsLoading={patientsState.loading}
          onGoToPatients={() => setActiveView('pacientes')}
        />
      )}

      {activeView === 'medicos' && session.profile?.name === 'administrador' && (
        <AdminDoctorsPage token={session.token} />
      )}

      {activeView === 'pacientes' && (
        <PatientsPage
          token={session.token}
          patients={patients}
          loading={patientsState.loading}
          error={patientsState.error}
          onRefresh={loadPatients}
          onCreatePatient={handleCreatePatient}
        />
      )}

      {activeView === 'agendamentos' && (
        <PlaceholderPage
          title="Agenda"
          description="Visualize e organize os próximos atendimentos em um só lugar."
        />
      )}

      {activeView === 'analise' && (
        <PlaceholderPage
          title="Consulta"
          description="Visualize informações importantes da consulta e acompanhe os registros do paciente."
        />
      )}

      {activeView === 'atendimentos' && (
        <PlaceholderPage
          title="Atendimentos"
          description="Consulte registros de atendimento e acompanhe a evolução clínica dos pacientes."
        />
      )}

      {activeView === 'relatorios' && (
        <PlaceholderPage
          title="Histórico"
          description="Acompanhe informações importantes registradas ao longo do cuidado."
        />
      )}

      {activeView === 'configuracoes' && (
        <PlaceholderPage
          title="Ajustes"
          description="Gerencie preferências básicas do painel."
        />
      )}
    </Layout>
  );
}

export default App;
