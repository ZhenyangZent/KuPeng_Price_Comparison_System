import type { HistoryPoint } from "./types";
import { formatTwd, formatUtc } from "./format";

interface Props { history: HistoryPoint[] }

export function HistoryChart({ history }: Props) {
  if (history.length === 0) {
    return <div className="empty-chart" role="status">尚無可繪製的價格觀測；空白不會補成 NT$0。</div>;
  }
  const width = 720;
  const height = 250;
  const padding = 34;
  const prices = history.map((point) => point.price_twd);
  const minimum = Math.min(...prices);
  const maximum = Math.max(...prices);
  const span = Math.max(1, maximum - minimum);
  const points = history.map((point, index) => {
    const x = history.length === 1 ? width / 2 : padding + (index / (history.length - 1)) * (width - padding * 2);
    const y = padding + ((maximum - point.price_twd) / span) * (height - padding * 2);
    return { ...point, x, y };
  });
  const label = `${history.length} 筆實際觀測，從 ${formatUtc(history[0].observed_at)} 到 ${formatUtc(history.at(-1)!.observed_at)}；觀測期間最低 ${formatTwd(minimum)}`;
  return (
    <figure className="chart-card">
      <svg className="history-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
        <defs>
          <linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2c6bed" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#2c6bed" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} className="axis" />
        <polygon points={`${points.map((point) => `${point.x},${point.y}`).join(" ")} ${points.at(-1)!.x},${height - padding} ${points[0].x},${height - padding}`} fill="url(#chart-fill)" />
        <polyline points={points.map((point) => `${point.x},${point.y}`).join(" ")} className="chart-line" />
        {points.map((point) => (
          <g key={`${point.observed_at}-${point.source_id}`}>
            <circle cx={point.x} cy={point.y} r="6" className="chart-dot"><title>{`${formatUtc(point.observed_at)}｜${formatTwd(point.price_twd)}`}</title></circle>
          </g>
        ))}
      </svg>
      <figcaption>{label}</figcaption>
    </figure>
  );
}
