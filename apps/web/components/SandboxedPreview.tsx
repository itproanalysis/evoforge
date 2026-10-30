type SandboxedPreviewProps = {
  html: string;
  title: string;
};

export function SandboxedPreview({ html, title }: SandboxedPreviewProps) {
  if (!html) {
    return <p>No preview available</p>;
  }
  return (
    <iframe
      sandbox=""
      srcDoc={html}
      title={title}
      referrerPolicy="no-referrer"
      style={{ width: "100%", height: 320, border: "1px solid #e5e8eb", borderRadius: 8 }}
    />
  );
}

export default SandboxedPreview;
