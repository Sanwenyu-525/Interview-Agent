export function TokenUsageCircle({ usage }) {
  const total = Number(usage?.total_tokens) || 0;
  const completion = Number(usage?.completion_tokens) || 0;
  const radius = 15;
  const circumference = 2 * Math.PI * radius;
  const filled = total > 0 ? (completion / total) * circumference : 0;
  const label = total >= 1000 ? `${(total / 1000).toFixed(1)}k` : String(total);
  return (
    <svg className="token-usage-circle" width="40" height="40" viewBox="0 0 40 40" role="img" aria-label={`Token 用量 ${total}`}>
      <circle className="token-usage-track" cx="20" cy="20" r={radius} />
      <circle className="token-usage-fill" cx="20" cy="20" r={radius} strokeDasharray={`${filled} ${circumference}`} />
      <text className="token-usage-label" x="20" y="20" textAnchor="middle" dominantBaseline="central">{label}</text>
    </svg>
  );
}
