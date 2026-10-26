import { useEffect, useRef } from 'react';

/** Served from frontend/public/demo/ (copied as-is by Vite). MP4 (H.264) plays in
 * Chrome, Edge, Firefox and Safari; WebM (VP9) covers browsers without H.264. */
export const DEMO_VIDEO_SOURCES = [
  { src: '/demo/foundryos-demo.mp4', type: 'video/mp4' },
  { src: '/demo/foundryos-demo.webm', type: 'video/webm' },
];

/**
 * Product walkthrough video in a modal. Closes with Esc, the close button or
 * a click on the backdrop; focus moves into the dialog and back afterwards.
 */
export function DemoVideoDialog({ open, onClose }) {
  const closeRef = useRef(null);
  const videoRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement;
    closeRef.current?.focus();
    const onKey = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      try {
        videoRef.current?.pause();
      } catch {
        // some test environments cannot pause media
      }
      previous?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="demo-dialog__backdrop" onClick={onClose} role="presentation">
      <div
        className="demo-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="demo-dialog-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="demo-dialog__header">
          <h2 id="demo-dialog-title">FoundryOS AI walkthrough</h2>
          <button ref={closeRef} type="button" className="button--ghost button--small" onClick={onClose}>
            Close
          </button>
        </header>
        {/* The walkthrough has no sound; captions are part of the picture. */}
        <video ref={videoRef} className="demo-dialog__video" controls autoPlay muted playsInline>
          {DEMO_VIDEO_SOURCES.map((source) => (
            <source key={source.src} src={source.src} type={source.type} />
          ))}
          Your browser cannot play this video.
        </video>
        <p className="muted small demo-dialog__note">
          Recorded on a test plant with synthetic demo data: admin, operator and supervisor views, and an AI-prepared
          maintenance request approved by a supervisor.
        </p>
      </div>
    </div>
  );
}