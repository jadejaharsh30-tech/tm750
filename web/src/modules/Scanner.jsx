/* ATH scanner.

   Three views for three cadences: Scan runs daily, Manage database is the
   audit and repair surface, Universe changes rarely.

   Deliberately not part of the snapshot pipeline. Its universe comes from an
   Excel upload, its prices from Yahoo, its profit data straight from the two
   source sheets -- so it runs on a day when no snapshot was uploaded at all. */
import { useState } from 'react';
import ScanView from './scanner/ScanView';
import ManageDb from './scanner/ManageDb';
import UniverseUpload from './scanner/UniverseUpload';
import './scanner/scanner.css';

const TABS = [
  { id: 'scan', label: 'Scanner' },
  { id: 'db', label: 'Manage database' },
  { id: 'universe', label: 'Universe' },
];

export default function Scanner() {
  const [tab, setTab] = useState('scan');

  return (
    <div className="module">
      <div className="tabs">
        <div className="tabs-list">
          {TABS.map((t) => (
            <button key={t.id} type="button"
                    className={`tab ${tab === t.id ? 'active' : ''}`}
                    onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'scan' && <ScanView />}
      {tab === 'db' && <ManageDb />}
      {tab === 'universe' && <UniverseUpload />}
    </div>
  );
}
