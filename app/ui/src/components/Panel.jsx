export function Panel({ as: Tag = 'section', className = '', fill = false, flush = false, children, ...rest }) {
  const classes = ['aa-panel', fill && 'aa-panel-fill', flush && 'aa-panel-flush', className].filter(Boolean).join(' ');
  return <Tag className={classes} {...rest}>{children}</Tag>;
}
