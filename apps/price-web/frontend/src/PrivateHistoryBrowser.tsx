import { FormEvent, useMemo, useState } from "react";
import { formatTwd, formatUtc } from "./format";
import { describeManualError, ManualObservationClient } from "./manualObservationClient";
import type { PrivateDetail, PrivateHistoryPoint, PrivateProduct, PrivateTrackQuality } from "./manualObservationTypes";

function HistoryTrack({ title, basis, raw, quality }: { title: string; basis: string; raw: PrivateHistoryPoint[]; quality: PrivateTrackQuality }) {
  return <section className="history-list private-history-track" aria-label={title} data-private-history-basis={basis}>
    <div className="section-heading"><div><p className="eyebrow">PRIVATE RAW + DAILY</p><h4>{title}</h4></div><span>{raw.length} 筆 raw · {quality.daily_representatives.length} 日</span></div>
    <div data-history-granularity="raw">{raw.length ? raw.map((point) => <div className="history-row" key={`${point.source_id}-${point.observed_at}`} data-price-twd={point.price_twd}><time dateTime={point.observed_at}>{formatUtc(point.observed_at)}</time><strong>{formatTwd(point.price_twd)}</strong><code>{point.source_id}</code></div>) : <p className="empty-row">沒有資料；不以零元或其他軌跡補值。</p>}</div>
    <div className="daily-history" data-history-granularity="daily">{quality.daily_representatives.map((point) => <div className="history-row" key={point.taipei_date} data-taipei-date={point.taipei_date} data-sample-count={point.sample_count}><time dateTime={point.taipei_date}>{point.taipei_date}</time><strong>{formatTwd(point.representative_price_twd)}</strong><span>{point.sample_count} 個 raw 樣本</span></div>)}</div>
  </section>;
}

function PrivateProductCard({ product, selected, onSelect }: { product: PrivateProduct; selected: boolean; onSelect: () => void }) {
  return <button type="button" className={`product-card private-product-card ${selected ? "selected" : ""}`} aria-pressed={selected} onClick={onSelect}>
    <span className="product-card-top"><span className="source-pill local">PRIVATE LOCAL</span><span>{formatUtc(product.observed_at)}</span></span>
    <strong>{product.title}</strong><span className="variant">{product.series_identity.product_id} · {product.series_identity.sku_id}</span>
    <span className="product-price">{formatTwd(product.before_coupon_price_twd)}</span><span className="timestamp">使用者手動記錄 · 非平台驗證</span>
  </button>;
}

export function PrivateHistoryBrowser() {
  const client = useMemo(() => new ManualObservationClient(), []), [query, setQuery] = useState(""), [items, setItems] = useState<PrivateProduct[]>([]), [selected, setSelected] = useState<string | null>(null), [detail, setDetail] = useState<PrivateDetail | null>(null), [busy, setBusy] = useState(false), [searched, setSearched] = useState(false), [error, setError] = useState("");
  const loadDetail = async (seriesKey: string) => { setSelected(seriesKey); setBusy(true); setError(""); try { setDetail(await client.detail(seriesKey)); } catch (caught) { setDetail(null); setError(describeManualError(caught)); } finally { setBusy(false); } };
  const search = async (event: FormEvent) => { event.preventDefault(); setBusy(true); setError(""); setDetail(null); setSelected(null); try { const result = await client.search(query.trim()); setItems(result.items); setSearched(true); } catch (caught) { setItems([]); setSearched(true); setError(describeManualError(caught)); } finally { setBusy(false); } };
  return <section className="private-history-browser" aria-label="已儲存的私人商品">
    <div className="section-heading"><div><p className="eyebrow">PRIVATE LOCAL · READ ONLY</p><h2>已儲存的私人商品</h2></div><span>不新增觀測</span></div>
    <p>重新開啟網站後，可依名稱、商品 ID 或 SKU 直接查詢先前手動保存的紀錄。此區與 B11 合成展示資料完全分開。</p>
    <form className="coupon-search private-history-search" role="search" aria-label="搜尋已儲存的私人商品" onSubmit={search}><label htmlFor="private-history-query">名稱、商品 ID 或 SKU</label><div><input id="private-history-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如 P-A14-REOPEN"/><button type="submit" disabled={busy}>{busy ? "讀取中…" : "搜尋私人紀錄"}</button><button type="button" className="secondary" onClick={() => { setQuery(""); setItems([]); setSelected(null); setDetail(null); setSearched(false); setError(""); }}>清除</button></div></form>
    {error && <div className="api-error" role="alert"><strong>私人歷史讀取失敗</strong><span>{error}</span></div>}
    {searched && !error && <p className="result-state" aria-live="polite">{items.length ? `找到 ${items.length} 個私人商品身分` : "查無私人商品；不回退合成展示資料。"}</p>}
    <div className="private-history-workspace"><aside className="product-list" aria-label="私人商品搜尋結果">{items.map((product) => <PrivateProductCard key={product.series_key} product={product} selected={selected === product.series_key} onSelect={() => void loadDetail(product.series_key)}/>)}</aside>
    <section className="private-history-detail" aria-label="私人商品歷史明細" data-private-history-container="true">{busy && selected && <p>讀取私人歷史…</p>}{!detail && !busy && <p className="detail-placeholder">從私人搜尋結果選擇商品；此動作只讀取資料。</p>}{detail && <><div className="detail-header"><div><span className="source-pill local">PRIVATE_LOCAL_USER_ENTERED</span><p className="eyebrow">NOT PLATFORM VERIFIED · CTA DISABLED</p><h3>{detail.product.title}</h3><p className="variant">{detail.product.series_identity.product_id} · {detail.product.series_identity.sku_id} · {detail.product.series_identity.seller_id}</p></div><div className="price-block"><span>最近券前觀測價</span><strong>{formatTwd(detail.product.before_coupon_price_twd)}</strong><small>{formatUtc(detail.product.observed_at)}</small></div></div>
      <div className="coupon-history-columns private-history-columns"><HistoryTrack title="券前歷史" basis="before_coupon" raw={detail.history.before_coupon} quality={detail.history_quality.before_coupon}/><HistoryTrack title="已確認券後歷史" basis="confirmed_after_coupon" raw={detail.history.confirmed_after_coupon} quality={detail.history_quality.confirmed_after_coupon}/><HistoryTrack title="使用者自報券後歷史" basis="user_reported_after_coupon" raw={detail.history.user_reported_after_coupon} quality={detail.history_quality.user_reported_after_coupon}/></div>
      <button type="button" className="cta" disabled>正式分潤連結尚未核准</button></>}
    </section></div>
  </section>;
}
