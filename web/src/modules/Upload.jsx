/* Data upload.

   Two steps deliberately: files are classified and previewed before anything
   is committed, so you see which source each file was recognised as, what
   date it will take, and which sources will be carried forward -- before the
   build runs rather than after it has already replaced a day.

   Any subset of the four files is valid. The profit workbooks are quarterly,
   so a normal daily upload is just the TradingView export. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { Empty, ErrorState, Loading } from '../components/ui';

const SOURCE_LABEL = {
  tradingview: 'TradingView export',
  screener: 'Screener.in export',
  profit_q: 'Quarterly profit workbook',
  profit_y: 'Annual profit workbook',
};

const DAILY = new Set(['tradingview', 'screener']);

export default function Upload({ onCommitted }) {
  const [files, setFiles] = useState([]);
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [overrideDate, setOverrideDate] = useState('');
  const [snaps, setSnaps] = useState(null);
  const inputRef = useRef(null);

  const loadSnaps = useCallback(() => {
    api.adminSnapshots().then(setSnaps).catch(() => {});
  }, []);
  useEffect(() => { loadSnaps(); }, [loadSnaps]);

  function pick(list) {
    const arr = [...list].filter((f) => /\.(csv|xlsx|xls)$/i.test(f.name));
    setFiles(arr);
    setPreview(null);
    setResult(null);
    setError(null);
    if (arr.length) runPreview(arr);
  }

  function runPreview(arr) {
    setPreviewing(true);
    const form = new FormData();
    arr.forEach((f) => form.append('files', f));
    api.uploadPreview(form)
      .then(setPreview)
      .catch((e) => setError(e))
      .finally(() => setPreviewing(false));
  }

  function commit({ replace = false, allowDuplicate = false } = {}) {
    setCommitting(true);
    setError(null);
    const form = new FormData();
    files.forEach((f) => form.append('files', f));
    if (overrideDate) form.append('snapshot_date', overrideDate);
    if (replace) form.append('replace', 'true');
    if (allowDuplicate) form.append('allow_duplicate', 'true');

    api.upload(form)
      .then((r) => {
        setResult(r);
        setFiles([]);
        setPreview(null);
        loadSnaps();
        onCommitted?.(r);
      })
      .catch(setError)
      .finally(() => setCommitting(false));
  }

  function removeSnapshot(date) {
    api.deleteSnapshot(date)
      .then(() => { loadSnaps(); onCommitted?.(); })
      .catch(setError);
  }

  return (
    <div className="module">
      <header className="module-head">
        <div>
          <div className="eyebrow">Daily update</div>
          <h1>Upload data</h1>
        </div>
      </header>

      {/* ------------------------------------------------------- dropzone */}
      <div
        className={`dropzone ${dragging ? 'over' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault(); setDragging(false); pick(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
      >
        <input ref={inputRef} type="file" multiple hidden
               accept=".csv,.xlsx,.xls"
               onChange={(e) => pick(e.target.files)} />
        <div className="dropzone-inner">
          <strong>Drop today's export files here</strong>
          <span className="muted">
            Any subset. Missing sources carry forward from the last snapshot
            that had them — the profit workbooks are quarterly, so a daily
            upload is usually just the TradingView file.
          </span>
        </div>
      </div>

      {files.length > 0 && (
        <div className="filelist">
          {files.map((f) => (
            <div className="fileitem" key={f.name}>
              <span className="mono ellipsis">{f.name}</span>
              <span className="subtle num">{(f.size / 1024).toFixed(0)} KB</span>
            </div>
          ))}
        </div>
      )}

      {previewing && <Loading label="Checking files" />}
      {error && <ErrorState error={error} />}

      {/* --------------------------------------------------- preview card */}
      {preview && !result && (
        <section className="card pad">
          {preview.ok === false ? (
            <>
              <div className="eyebrow" style={{ color: 'var(--down)' }}>
                Cannot use these files
              </div>
              <p className="tight">{preview.error}</p>
            </>
          ) : (
            <>
              <div className="card-head">
                <div className="eyebrow">Ready to commit</div>
                <span className="subtle num">
                  {preview.snapshots_held} snapshot(s) held
                </span>
              </div>

              <div className="prevgrid">
                <div className="prevcell">
                  <span className="eyebrow small">Snapshot date</span>
                  <span className="num prevcell-v">
                    {overrideDate || preview.snapshot_date}
                  </span>
                  <input className="filter-val" type="date" value={overrideDate}
                         onChange={(e) => setOverrideDate(e.target.value)} />
                </div>
                <div className="prevcell">
                  <span className="eyebrow small">Recognised</span>
                  {Object.entries(preview.recognised).map(([k, v]) => (
                    <span className="prevline" key={k}>
                      <span className="ok-dot" />
                      <span>{SOURCE_LABEL[k]}</span>
                      <span className="subtle mono ellipsis">{v}</span>
                    </span>
                  ))}
                </div>
                <div className="prevcell">
                  <span className="eyebrow small">Carried forward</span>
                  {Object.keys(preview.carried_forward).length === 0
                    ? <span className="subtle">Nothing — all four supplied</span>
                    : Object.entries(preview.carried_forward).map(([k, from]) => (
                      <span className="prevline" key={k}>
                        <span className={`ok-dot ${DAILY.has(k) ? 'warn' : 'carry'}`} />
                        <span>{SOURCE_LABEL[k]}</span>
                        <span className="subtle">from {from}</span>
                      </span>
                    ))}
                </div>
              </div>

              {Object.keys(preview.carried_forward).some((k) => DAILY.has(k)) && (
                <div className="banner compact">
                  <strong>A daily source is being carried forward.</strong>{' '}
                  Price and screener data normally change every day — this
                  snapshot will repeat the previous values for that source.
                </div>
              )}

              {preview.duplicate_of && (
                <div className="banner compact">
                  <strong>These files match snapshot {preview.duplicate_of}.</strong>{' '}
                  Committing would add a day showing zero change and distort
                  day-over-day comparisons.
                </div>
              )}

              {preview.already_exists && (
                <div className="banner compact">
                  <strong>{preview.snapshot_date} already exists.</strong>{' '}
                  Committing will rebuild it in place.
                </div>
              )}

              <div className="crash-actions">
                <button className="btn primary" disabled={committing}
                        onClick={() => commit({
                          replace: preview.already_exists,
                          allowDuplicate: Boolean(preview.duplicate_of),
                        })}>
                  {committing ? 'Building…'
                    : preview.already_exists ? 'Rebuild this snapshot'
                    : 'Commit snapshot'}
                </button>
                <button className="btn subtle-btn" disabled={committing}
                        onClick={() => { setFiles([]); setPreview(null); }}>
                  Cancel
                </button>
              </div>
              {committing && (
                <p className="note">
                  Building takes around 20 seconds. Nothing is replaced until
                  it passes validation.
                </p>
              )}
            </>
          )}
        </section>
      )}

      {/* ---------------------------------------------------------- result */}
      {result && (
        <section className="card pad">
          <div className="eyebrow" style={{ color: 'var(--up)' }}>
            Committed
          </div>
          <p className="tight">
            Snapshot <strong className="num">
              {result.manifest?.snapshot_date}</strong> built with{' '}
            <span className="num">{result.manifest?.universe}</span> companies
            across <span className="num">{result.manifest?.columns}</span>{' '}
            columns. {result.snapshots?.length} snapshot(s) now held.
          </p>
          <button className="btn" onClick={() => setResult(null)}>
            Upload another
          </button>
        </section>
      )}

      {/* ------------------------------------------------- held snapshots */}
      <section className="card pad">
        <div className="card-head">
          <div className="eyebrow">Snapshots held</div>
          <span className="subtle num">{snaps?.n ?? '—'}</span>
        </div>
        {!snaps ? <Loading label="Loading" />
          : snaps.snapshots.length === 0 ? (
            <Empty title="No snapshots" hint="Upload a file to create the first." />
          ) : (
            <div className="snaplist">
              <div className="snaprow snaprow-head eyebrow">
                <span>Date</span><span className="num">Companies</span>
                <span className="num">Columns</span><span>Carried forward</span>
                <span className="num">Size</span><span />
              </div>
              {[...snaps.snapshots].reverse().map((s) => (
                <div className="snaprow" key={s.snapshot_date}>
                  <span className="mono strong">{s.snapshot_date}</span>
                  <span className="num">{s.universe ?? '--'}</span>
                  <span className="num subtle">{s.columns ?? '--'}</span>
                  <span className="subtle ellipsis">
                    {s.carried_forward?.length
                      ? s.carried_forward.map((k) => SOURCE_LABEL[k] ?? k).join(', ')
                      : '—'}
                  </span>
                  <span className="num subtle">{s.size_kb} KB</span>
                  <button className="filter-x"
                          disabled={snaps.snapshots.length < 2}
                          title={snaps.snapshots.length < 2
                            ? 'Cannot delete the only snapshot'
                            : `Delete ${s.snapshot_date}`}
                          onClick={() => removeSnapshot(s.snapshot_date)}>
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
        <p className="note">
          Raw files are archived per snapshot, so any day can be rebuilt from
          its own inputs. Deleting a snapshot removes the built data, not the
          archived source files.
        </p>
      </section>
    </div>
  );
}
