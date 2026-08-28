import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { setAsOf } from './api/client';
import ErrorBoundary from './components/ErrorBoundary';
import './theme.css';
import './app.css';

// Restore before mount: the catalog loads immediately, and it must load for
// the selected date rather than for latest and then be corrected.
setAsOf(sessionStorage.getItem('tm750-asof'));

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary where="The app">
      <App />
    </ErrorBoundary>
  </StrictMode>
);
