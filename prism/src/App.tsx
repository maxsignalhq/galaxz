import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';

import { Landing }        from './pages/Landing';
import { Dashboard }      from './pages/Dashboard';
import { DevConsole }     from './pages/DevConsole';
import { TaskUI }         from './pages/TaskUI';
import { ReviewQueue }    from './pages/ReviewQueue';
import { OrionAnalytics } from './pages/OrionAnalytics';
import { Settings }       from './pages/Settings';

export default function App() {
  return (
    <Routes>
      <Route path="/"             element={<Landing />} />
      <Route path="/dashboard"    element={<Dashboard />} />
      <Route path="/dev-console"  element={<DevConsole />} />
      <Route path="/task-ui"      element={<TaskUI />} />
      <Route path="/review-queue" element={<ReviewQueue />} />
      <Route path="/orion"        element={<OrionAnalytics />} />
      <Route path="/settings"     element={<Settings />} />
      <Route path="*"             element={<Navigate to="/" replace />} />
    </Routes>
  );
}
