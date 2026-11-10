export function Card({
  as: Tag = 'article',
  className = '',
  selected = false,
  interactive = false,
  children,
  ...rest
}) {
  const classes = [
    'aa-card',
    interactive && 'is-interactive',
    selected && 'is-selected',
    className,
  ].filter(Boolean).join(' ');
  return <Tag className={classes} {...rest}>{children}</Tag>;
}
