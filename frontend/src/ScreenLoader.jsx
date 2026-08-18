function ScreenLoader({ message, subtext }) {
  if (!message) return null
  return (
    <div className="screen-loader" role="status" aria-live="polite">
      <div className="screen-loader-card">
        <span className="screen-loader-ring" />
        <p className="screen-loader-message">{message}</p>
        {subtext ? <p className="screen-loader-sub">{subtext}</p> : null}
      </div>
    </div>
  )
}

export default ScreenLoader
