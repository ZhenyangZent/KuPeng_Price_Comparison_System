import { formatTwd, formatUtc } from "./format";

interface CouponHistoryPoint { observed_at: string; price_twd: number; source_id: string }
interface Props {
  before: CouponHistoryPoint[];
  after: CouponHistoryPoint[];
}

interface DrawPoint extends CouponHistoryPoint { x: number; y: number }

export function CouponHistoryChart({ before, after }: Props) {
  if (before.length === 0 && after.length === 0) {
    return <div className="empty-chart" role="status">券前與已確認券後歷史皆無樣本；未知值不會補成 NT$0。</div>;
  }
  const width = 720, height = 280, padding = 38;
  const all = [...before, ...after];
  const timestamps = [...new Set(all.map((item) => item.observed_at))].sort((a, b) => Date.parse(a) - Date.parse(b));
  const prices = all.map((item) => item.price_twd), minimum = Math.min(...prices), maximum = Math.max(...prices), span = Math.max(1, maximum - minimum);
  const points = (series: CouponHistoryPoint[]): DrawPoint[] => series.map((item) => ({
    ...item,
    x: timestamps.length === 1 ? width / 2 : padding + (timestamps.indexOf(item.observed_at) / (timestamps.length - 1)) * (width - padding * 2),
    y: padding + ((maximum - item.price_twd) / span) * (height - padding * 2)
  }));
  const beforePoints = points(before), afterPoints = points(after);
  const polyline = (series: DrawPoint[], className: string, label: string) => series.length === 0 ? null : <>
    <polyline points={series.map((point) => `${point.x},${point.y}`).join(" ")} className={className}/>
    {series.map((point) => <circle key={`${label}-${point.observed_at}-${point.source_id}`} cx={point.x} cy={point.y} r="6" className={`${className}-dot`}><title>{`${label}｜${formatUtc(point.observed_at)}｜${formatTwd(point.price_twd)}`}</title></circle>)}
  </>;
  return <figure className="chart-card coupon-chart-card">
    <div className="chart-legend" aria-label="價格歷史圖例"><span className="before">券前商品價</span><span className="after">已確認券後商品價</span></div>
    <svg className="history-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`券前 ${before.length} 筆、已確認券後 ${after.length} 筆；兩條序列分開保存`}>
      <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} className="axis" />
      {polyline(beforePoints, "coupon-line-before", "券前")}
      {polyline(afterPoints, "coupon-line-after", "券後")}
    </svg>
    <figcaption>券前 {before.length} 筆／已確認券後 {after.length} 筆；歷史券價不代表目前優惠仍有效。</figcaption>
  </figure>;
}
