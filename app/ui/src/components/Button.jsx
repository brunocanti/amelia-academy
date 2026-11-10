export function Button({
  variant = 'secondary',
  className = '',
  type,
  children,
  ...rest
}) {
  const classes = ['aa-btn', `aa-btn-${variant}`, className].filter(Boolean).join(' ');
  return (
    <button type={type || 'button'} className={classes} {...rest}>
      {children}
    </button>
  );
}
