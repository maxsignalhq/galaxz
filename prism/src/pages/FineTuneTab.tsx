import React from 'react';
interface Props { onCountChange: (n: number) => void; }
export function FineTuneTab({ onCountChange }: Props) {
  React.useEffect(() => { onCountChange(0); }, []);
  return <div className="ft-panel"><div className="ft-empty"><span className="ft-empty-icon">✦</span><span className="ft-empty-text">Loading…</span></div></div>;
}
export default FineTuneTab;
