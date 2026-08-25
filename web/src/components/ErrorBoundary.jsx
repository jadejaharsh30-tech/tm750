/* A render error unmounts the whole React tree and leaves a blank page with
   nothing in the console the user would think to look at. This catches it and
   shows what broke, so a bug is never invisible. */
import { Component } from 'react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    console.error('[tm750] render error', error, info);
  }

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="crash">
        <div className="crash-box">
          <div className="eyebrow" style={{ color: 'var(--down)' }}>
            Something broke while rendering
          </div>
          <h2>{this.props.where ?? 'This view'} could not be displayed</h2>
          <p className="muted">
            The data loaded, but the page failed to draw it. The detail below
            says where.
          </p>
          <pre className="crash-detail">{String(error?.message ?? error)}</pre>
          {info?.componentStack && (
            <details>
              <summary className="muted">Component stack</summary>
              <pre className="crash-detail">
                {info.componentStack.trim().split('\n').slice(0, 8).join('\n')}
              </pre>
            </details>
          )}
          <div className="crash-actions">
            <button className="btn"
                    onClick={() => this.setState({ error: null, info: null })}>
              Try again
            </button>
            <button className="btn subtle-btn"
                    onClick={() => window.location.reload()}>
              Reload page
            </button>
          </div>
        </div>
      </div>
    );
  }
}
