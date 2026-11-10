// Model answers come as light Markdown. Show headings, bold and lists as text, not as symbols.
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, i) => part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : part.startsWith('*') && part.endsWith('*') ? <em key={i}>{part.slice(1, -1)}</em> : part);
}

export function Prose({ text }) {
  const blocks = String(text || '').split(/\n{2,}/).map((b) => b.trim()).filter((b) => b && !/^[-*_]{3,}$/.test(b));
  return <div className="prose">{blocks.map((block, i) => {
    const lines = block.split('\n');
    if (/^#{1,6}\s/.test(block)) return <p key={i}><strong>{inline(block.replace(/^#{1,6}\s+/, '').replace(/\*\*/g, ''))}</strong></p>;
    if (lines.every((l) => /^\s*([-*]|\d+\.)\s/.test(l))) return <ul key={i}>{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*([-*]|\d+\.)\s+/, ''))}</li>)}</ul>;
    return <p key={i}>{lines.map((l, j) => <span key={j}>{j > 0 && <br />}{inline(l.replace(/^#{1,6}\s+/, ''))}</span>)}</p>;
  })}</div>;
}
