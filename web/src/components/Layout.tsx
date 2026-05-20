import { type ReactNode, useEffect, useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { fetchHealth } from '../api';

export default function Layout({ children }: { children: ReactNode }) {
  const [snapshotDate, setSnapshotDate] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then((h) => setSnapshotDate(h.latest_snapshot_date))
      .catch(() => {
        // health endpoint failures are silent in the header
      });
    return () => controller.abort();
  }, []);

  return (
    <div className="app">
      <header className="site-header">
        <div className="brand">
          <Link to="/" className="brand-link">
            close encounters
          </Link>
          <span className="brand-tag">near-Earth object watch</span>
        </div>
        <nav className="site-nav">
          <NavLink to="/" end>
            Upcoming
          </NavLink>
          <NavLink to="/alerts">Noteworthy</NavLink>
          <NavLink to="/risk">Risk</NavLink>
        </nav>
        {snapshotDate && (
          <span className="snapshot-badge" title="Latest snapshot in the warehouse">
            data as of {snapshotDate}
          </span>
        )}
      </header>

      <main className="site-main">{children}</main>

      <footer className="site-footer">
        <p>
          Sourced from{' '}
          <a href="https://cneos.jpl.nasa.gov/" rel="noopener noreferrer">
            NASA/JPL CNEOS
          </a>{' '}
          and the{' '}
          <a href="https://ssd.jpl.nasa.gov/" rel="noopener noreferrer">
            JPL Small-Body Database
          </a>
          . Data licensed{' '}
          <a href="https://creativecommons.org/licenses/by/4.0/" rel="noopener noreferrer">
            CC BY 4.0
          </a>
          .
        </p>
        <p className="footer-feeds">
          Feeds: <a href="/upcoming.rss">upcoming RSS</a> ·{' '}
          <a href="/upcoming.json">upcoming JSON</a> ·{' '}
          <a href="/noteworthy.rss">noteworthy RSS</a> ·{' '}
          <a href="/noteworthy.json">noteworthy JSON</a>
        </p>
      </footer>
    </div>
  );
}
