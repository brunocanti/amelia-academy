import React from 'react';
import { createRoot } from 'react-dom/client';
import './app.css';
import './components/surfaces.css';
import './prototype.css';
import { App } from './App.jsx';
import { I18nProvider } from './i18n/index.jsx';
import { ThemeProvider } from './theme.jsx';
import { ProjectProvider } from './ProjectContext.jsx';

createRoot(document.getElementById('app')).render(
  <React.StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <ProjectProvider>
          <App />
        </ProjectProvider>
      </I18nProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
