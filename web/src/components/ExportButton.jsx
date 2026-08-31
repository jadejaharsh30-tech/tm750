/* Download the current table as Excel.

   Deliberately dumb: it hands the server the same columns, filters and sort
   the page is already using, and the server re-runs the query. Nothing is
   built from what happens to be rendered, so a virtualised table that has
   only 30 rows in the DOM still exports all of them.

   The failure state is inline rather than a thrown error, because a failed
   download should not take the table down with it. */
import { useState } from 'react';
import { api } from '../api/client';

export default function ExportButton({
  columns,
  filters = [],
  sort = null,
  filename = 'tm750-export',
  sheetTitle = 'Data',
  context = null,
  disabled = false,
  label = 'Excel',
}) {
  const [state, setState] = useState('idle');   // idle | working | error
  const [message, setMessage] = useState(null);

  async function run() {
    if (state === 'working') return;
    setState('working');
    setMessage(null);
    try {
      await api.exportXlsx({
        columns,
        filters,
        sort: sort ? [sort] : [],
        limit: 750,
        include_total: false,
        filename,
        sheet_title: sheetTitle,
        ...(context ? { context } : {}),
      });
      setState('idle');
    } catch (err) {
      setState('error');
      setMessage(err?.message ?? 'Export failed.');
    }
  }

  return (
    <span className="exportbtn">
      <button className="btn" onClick={run}
              disabled={disabled || state === 'working'}
              title="Download these rows and columns as an .xlsx file">
        {state === 'working' ? 'Preparing…' : label}
      </button>
      {state === 'error' && (
        <span className="export-err subtle" role="alert" title={message}>
          {message}
        </span>
      )}
    </span>
  );
}
