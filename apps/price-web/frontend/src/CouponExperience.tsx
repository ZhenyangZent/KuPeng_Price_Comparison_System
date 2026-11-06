import { useMemo, useState } from "react";
import { COUPON_FIXTURES } from "./couponFixtures";
import { CouponHistoryChart } from "./CouponHistoryChart";
import { toCouponPriceView } from "./couponUiAdapter";
import { formatTwd, formatUtc } from "./format";

export function CouponFixtureExperience() {
  const [selectedId, setSelectedId] = useState(() => {
    const requested = new URLSearchParams(location.search).get("coupon");
    const match = COUPON_FIXTURES.find((item) => item.series_identity.product_id === `SYN-P-${requested}`);
    return match?.series_identity.product_id ?? COUPON_FIXTURES[0].series_identity.product_id;
  });
  const selected = useMemo(() => COUPON_FIXTURES.find((item) => item.series_identity.product_id === selectedId) ?? COUPON_FIXTURES[0], [selectedId]);
  const view = toCouponPriceView(selected);
  return <main className="coupon-main">
    <section className="safety-banner synthetic"><strong>SYNTHETIC V4 OPT-IN ONLY</strong><span>此頁不讀取真實酷澎資料；優惠券、商品、SKU、賣家與資格均為合成證據。</span></section>
    <section className="workspace coupon-workspace">
      <aside className="results-panel" aria-label="優惠券合成案例">
        <div className="section-heading"><div><p className="eyebrow">V4 COUPON CASES</p><h2>優惠狀態案例</h2></div></div>
        <div className="product-list">{COUPON_FIXTURES.map((item) => {
          const itemView = toCouponPriceView(item);
          return <button key={item.series_identity.product_id} className={`product-card ${item.series_identity.product_id === selectedId ? "selected" : ""}`} onClick={() => setSelectedId(item.series_identity.product_id)} aria-pressed={item.series_identity.product_id === selectedId} type="button">
            <span className="product-card-top"><span className={`source-pill ${itemView.confirmed ? "confirmed" : "warning"}`}>{itemView.statusLabel}</span><span>{item.history.before_coupon.length + item.history.confirmed_after_coupon.length} 筆</span></span>
            <strong>{item.series_identity.product_id.replace("SYN-P-", "SYNTHETIC｜")}</strong>
            <span className="variant">{item.series_identity.sku_id} · {item.series_identity.seller_id}</span>
            <span className="product-price">{itemView.primaryPrice === null ? "價格未知" : formatTwd(itemView.primaryPrice)}</span>
            <span className="timestamp">{itemView.primaryLabel}</span>
          </button>;
        })}</div>
      </aside>
      <section className="detail-panel coupon-detail" aria-live="polite">
        <div className="detail-header"><div><span className={`source-pill ${view.confirmed ? "confirmed" : "warning"}`}>{view.statusLabel}</span><p className="eyebrow">EXACT SERIES · {selected.schema_version}</p><h2>{selected.series_identity.product_id}</h2><p className="variant">{selected.series_identity.package_signature} · {selected.series_identity.condition}</p></div><div className="price-block"><span>{view.primaryLabel}</span><strong>{view.primaryPrice === null ? "價格未知" : formatTwd(view.primaryPrice)}</strong><small>{formatUtc(selected.observed_at)}</small></div></div>
        <div className="status-row"><span className="status-badge"><b>券前價</b>{view.basePrice === null ? "UNKNOWN" : formatTwd(view.basePrice)}</span><span className={`status-badge ${view.confirmed ? "" : "warning"}`}><b>券資格</b>{view.statusLabel}</span><span className="status-badge warning"><b>運費</b>{selected.shipping_status}</span><span className="status-badge"><b>金額口徑</b>{selected.price_basis.amount_basis} × {selected.price_basis.quantity}</span></div>
        {view.possiblePrice !== null && <div className="coupon-warning" role="note"><b>可能券後價 {formatTwd(view.possiblePrice)} 不會作為主價。</b><span>尚需領券或重新驗證資格、效期與適用範圍。</span></div>}
        {!view.confirmed && selected.coupon.status !== "NONE" && view.possiblePrice === null && <div className="coupon-warning" role="note"><b>{view.statusLabel}，優惠券不計入主價。</b><span>過期、不適用或未知條件不會冒充已確認折抵。</span></div>}
        {view.primaryPrice === 0 && <div className="zero-warning" role="note"><b>已確認券後商品價為 NT$0，但不是零成本到手。</b><span>運費與必要費用仍為 UNKNOWN；required_total_twd 維持 null。</span></div>}
        <div className="coupon-proof-grid"><article><span>商品／SKU／賣家</span><strong>{selected.series_identity.product_id}</strong><code>{selected.series_identity.sku_id} · {selected.series_identity.seller_id}</code></article><article><span>優惠券／資格</span><strong>{selected.coupon.coupon_id ?? "UNKNOWN"}</strong><code>{selected.coupon.eligibility_profile ?? "UNKNOWN"}</code></article><article><span>適用證據</span><strong>{selected.coupon.scope_evidence ?? "UNKNOWN"}</strong><code>{selected.source_id}</code></article></div>
        <CouponHistoryChart before={selected.history.before_coupon} after={selected.history.confirmed_after_coupon}/>
        <div className="coupon-history-columns"><section className="history-list" aria-label="券前商品價歷史"><div className="section-heading"><div><p className="eyebrow">BEFORE COUPON</p><h3>券前商品價歷史</h3></div><span>{selected.history.before_coupon.length} 筆</span></div>{selected.history.before_coupon.length === 0 ? <p className="empty-row">沒有已驗證券前樣本。</p> : selected.history.before_coupon.map((item) => <div className="history-row coupon-history-row" key={item.source_id}><time dateTime={item.observed_at}>{formatUtc(item.observed_at)}</time><strong>{formatTwd(item.price_twd)}</strong><code>{item.source_id}</code></div>)}</section><section className="history-list" aria-label="已確認券後商品價歷史"><div className="section-heading"><div><p className="eyebrow">CONFIRMED AFTER COUPON</p><h3>已確認券後商品價歷史</h3></div><span>{selected.history.confirmed_after_coupon.length} 筆</span></div>{selected.history.confirmed_after_coupon.length === 0 ? <p className="empty-row">沒有已確認券後樣本；可能價格不會寫入此序列。</p> : selected.history.confirmed_after_coupon.map((item) => <div className="history-row coupon-history-row" key={item.source_id}><time dateTime={item.observed_at}>{formatUtc(item.observed_at)}</time><strong>{formatTwd(item.price_twd)}</strong><code>{item.coupon_id}</code></div>)}</section></div>
        <article className="affiliate-card coupon-cta"><p className="eyebrow">OUTBOUND DISABLED</p><h3>推薦／分潤連結</h3><button className="cta" disabled type="button">正式連結尚未核准</button><small>確認券有效不等於已取得台灣官方商品級分潤、redirect 或 runtime 授權。</small></article>
      </section>
    </section>
  </main>;
}
