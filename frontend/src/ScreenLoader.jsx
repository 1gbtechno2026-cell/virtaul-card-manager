function ScreenLoader({ message, subtext }) {
  if (!message) return null
  return (
    <div className="screen-loader" role="status" aria-live="polite">
      <div className="screen-loader-card">
        <div className="card-loader">
          <div className="card-loader-shine" />
          <div className="card-loader-top">
            <span className="card-loader-chip" />
            <span className="card-loader-brand" />
          </div>
          <div className="card-loader-number">
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="card-loader-bottom">
            <span className="card-loader-line card-loader-line-wide" />
            <span className="card-loader-line card-loader-line-narrow" />
          </div>
        </div>
        <p className="screen-loader-message">{message}</p>
        {subtext ? <p className="screen-loader-sub">{subtext}</p> : null}
      </div>
    </div>
  )
}

export default ScreenLoader
