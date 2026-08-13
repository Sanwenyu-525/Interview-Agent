export function PageHeader({ kicker, title, description, status, actions }) {
  return (
    <header className="page-header">
      <div className="page-header-copy">
        {kicker ? <span className="view-kicker">{kicker}</span> : null}
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {(status || actions) ? (
        <div className="page-header-actions">
          {status ? <span className="page-header-status">{status}</span> : null}
          {actions}
        </div>
      ) : null}
    </header>
  );
}
