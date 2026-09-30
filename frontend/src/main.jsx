/**
 * React application entry point.
 *
 * This is a minimal stub so the Vite build can resolve the entry module.
 * Frontend Member 1 owns the full UI implementation.
 * This file is intentionally minimal — do not add presentation code here.
 *
 * The integration layer (hooks, api, store) is already complete and
 * fully tested. Member 1 imports from:
 *   import { useTask, useTaskEvents, useTaskList, useRecipes,
 *            useMetrics, useHealth, useFeedback, useTaskResult } from './hooks';
 *   import { useAgentStore } from './store/agentStore.js';
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
