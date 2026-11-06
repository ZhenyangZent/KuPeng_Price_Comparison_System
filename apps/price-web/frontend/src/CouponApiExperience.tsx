import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { adaptB10Product, detailTruncationWarning } from "./b10Adapter";
import type { B10DetailResponse, B10Product, B10SearchResponse } from "./b10WireTypes";
import { CouponHistoryChart } from "./CouponHistoryChart";
import { BatchImportPanel } from "./BatchImportPanel";
import { CouponV4Client, describeV4Error } from "./couponV4Client";
import { formatTwd, formatUtc } from "./format";
import { ManualObservationPanel } from "./ManualObservationPanel";
import { PrivateHistoryBrowser } from "./PrivateHistoryBrowser";

type LoadState = "LOADING" | "READY" | "EMPTY" | "NO_MATCH" | "ERROR";
type DetailState = "IDLE" | "LOADING" | "READY" | "ERROR";

export function CouponApiExperience() {
  const client = useMemo(() => new CouponV4Client(), []);
  const initial = useMemo(() => new URLSearchParams(location.search), []);
  const [query, setQuery] = useState(initial.get("q") ?? ""), [submitted, setSubmitted] = useState(initial.get("q") ?? "");
  const [search, setSearch] = useState<B10SearchResponse | null>(null), [items, setItems] = useState<B10Product[]>([]);
  const [selected, setSelected] = useState<string | null>(initial.get("series")), [detail, setDetail] = useState<B10DetailResponse | null>(null);
  const [listState, setListState] = useState<LoadState>("LOADING"), [detailState, setDetailState] = useState<DetailState>("IDLE");
  const [error, setError] = useState(""), [retry, setRetry] = useState(0);
  const listSequence = useRef(0), detailSequence = useRef(0);

  useEffect(() => {
    const controller = new AbortController(), sequence = ++listSequence.current;
    setListState("LOADING"); setError("");
    client.search(submitted, controller.signal).then((response) => {
      if (sequence !== listSequence.current) return;
      setSearch(response); setItems(response.items);
      const next = selected && response.items.some((item) => item.series_key === selected) ? selected : response.items[0]?.series_key ?? null;
      setSelected(next); setListState(response.total ? "READY" : submitted ? "NO_MATCH" : "EMPTY");
    }).catch((caught) => { if (controller.signal.aborted || sequence !== listSequence.current) return; setSearch(null); setItems([]); setSelected(null); setDetail(null); setError(describeV4Error(caught)); setListState("ERROR"); });
    return () => controller.abort();
  }, [client, submitted, retry]);

  useEffect(() => {
    const parameters = new URLSearchParams(location.search); parameters.set("mode", "synthetic"); parameters.set("contract", "v4"); parameters.delete("source");
    if (submitted) parameters.set("q", submitted); else parameters.delete("q");
    if (selected) parameters.set("series", selected); else parameters.delete("series");
    history.replaceState({}, "", `${location.pathname}?${parameters}`);
    if (!selected || !search) { setDetail(null); setDetailState("IDLE"); return; }
    const expected = search.items.find((item) => item.series_key === selected);
    if (!expected) { setDetail(null); setDetailState("ERROR"); setError("選取商品不在同一份 Search 快照"); return; }
    const controller = new AbortController(), sequence = ++detailSequence.current;
    setDetailState("LOADING"); setDetail(null); setError("");
    client.detail(selected, expected, search, controller.signal).then((response) => { if (sequence === detailSequence.current) { setDetail(response); setDetailState("READY"); } }).catch((caught) => { if (controller.signal.aborted || sequence !== detailSequence.current) return; setError(describeV4Error(caught)); setDetailState("ERROR"); });
    return () => controller.abort();
  }, [client, search, selected, submitted, retry]);

  const searchFor = (raw: string) => { const next = raw.trim(); setQuery(next); if (next === submitted) setRetry((value) => value + 1); else setSubmitted(next); };
  const submit = (event: FormEvent) => { event.preventDefault(); searchFor(query); };
  const searchWithEnter = (event: KeyboardEvent<HTMLInputElement>) => { if (event.key === "Enter") { event.preventDefault(); searchFor(event.currentTarget.value); } };
  const retryNow = () => setRetry((value) => value + 1);
  const view = detail ? adaptB10Product(detail.product) : null;
  const truncation = detail ? detailTruncationWarning(detail) : null;

  return <main className="coupon-main">
    <section className="safety-banner local"><strong>B11 WSGI · SYNTHETIC API</strong><span>相容既有 `B10 WSGI · SYNTHETIC API` V4 wire；畫面透過同源 `/cdh-coupon-v4` proxy 實際讀取本機唯讀 Search／Detail，API 失敗時不回退至 fixture。</span></section>
    <section className="data-classification-guide" aria-label="價格資料分類說明">
      <div><span className="source-pill synthetic">SYNTHETIC DEMO</span><strong>離線合成展示</strong><p>只用於功能展示，不代表即時酷澎價格。</p></div>
      <div><span className="source-pill local">PRIVATE USER-REPORTED</span><strong>本機私人自報</strong><p>由使用者手動輸入或匯入，不是平台驗證。</p></div>
      <div><span className="source-pill confirmed">PLATFORM CONFIRMED</span><strong>證據完整才成立</strong><p>券、資格、效期、範圍與來源皆通過才可顯示。</p></div>
    </section>
    <BatchImportPanel/>
    <ManualObservationPanel/>
    <PrivateHistoryBrowser/>
    <form className="coupon-search" role="search" onSubmit={submit}><label htmlFor="coupon-api-search">搜尋 B10 商品、SKU 或商品 ID</label><div><input id="coupon-api-search" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={searchWithEnter} placeholder="例如 SYN-SKU-1"/><button type="submit">查詢 V4 API</button><button className="secondary" type="button" onClick={() => { setQuery(""); setSubmitted(""); }}>清除</button></div></form>
    {listState === "ERROR" && <section className="api-error" role="alert"><strong>V4 Search 失敗，未載入示範資料</strong><span>{error}</span><button type="button" onClick={retryNow}>重試 API</button></section>}
    <section className="workspace coupon-workspace">
      <aside className="results-panel" aria-label="B10 V4 搜尋結果"><div className="section-heading"><div><p className="eyebrow">ACTUAL V4 SEARCH</p><h2>精確商品序列</h2></div></div><p className="result-state" aria-live="polite">{listState === "LOADING" ? "讀取 B10 Search…" : listState === "EMPTY" ? "V4 snapshot 沒有商品" : listState === "NO_MATCH" ? "V4 snapshot 有商品，但查無符合結果" : listState === "READY" ? `${items.length}／${search?.total ?? 0} 個序列 · ${search?.data_version ?? ""}` : "未載入"}</p><div className="product-list">{items.map((product) => { const itemView = adaptB10Product(product); return <button type="button" key={product.series_key} className={`product-card ${selected === product.series_key ? "selected" : ""}`} aria-pressed={selected === product.series_key} onClick={() => setSelected(product.series_key)}><span className="product-card-top"><span className={`source-pill ${itemView.confirmed ? "confirmed" : product.display_basis === "PRICE_UNAVAILABLE" ? "warning" : "local"}`}>{itemView.couponStatusLabel}</span><span>min {product.minimum_purchase_quantity}</span></span><strong>{product.title}</strong><span className="variant">{product.series_identity.sku_id} · {product.series_identity.seller_id}</span><span className="product-price">{itemView.primaryPrice === null ? "價格未知" : formatTwd(itemView.primaryPrice)}</span><span className="timestamp">{itemView.primaryLabel}</span></button>; })}</div></aside>
      <section className="detail-panel coupon-detail" aria-live="polite">
        {detailState === "IDLE" && <div className="detail-placeholder">請選擇 V4 商品序列</div>}
        {detailState === "LOADING" && <div className="detail-placeholder">讀取同一 series_key 的 B10 Detail…</div>}
        {detailState === "ERROR" && <div className="api-error" role="alert"><strong>V4 Detail 失敗，未顯示 fixture</strong><span>{error}</span><button type="button" onClick={retryNow}>重試 Search＋Detail</button></div>}
        {detailState === "READY" && detail && view && <><div className="detail-header"><div><span className={`source-pill ${view.confirmed ? "confirmed" : view.sourceUsable ? "local" : "warning"}`}>{view.sourceUsable ? view.couponStatusLabel : "來源權限失效"}</span><p className="eyebrow">{detail.product.series_key} · {detail.schema_version}</p><h2>{detail.product.title}</h2><p className="variant">{detail.product.series_identity.product_id} · {detail.product.series_identity.sku_id} · {detail.product.series_identity.seller_id}</p></div><div className="price-block"><span>{view.primaryLabel}</span><strong>{view.primaryPrice === null ? "價格未知" : formatTwd(view.primaryPrice)}</strong><small>{formatUtc(detail.product.observed_at)}</small></div></div>
        <div className="checkout-boundary" role="note" aria-label="這是商品觀測價，不是結帳總額"><strong>這是商品觀測價，不是結帳總額。</strong><span>最低數量 {detail.product.minimum_purchase_quantity}；運費／必要費用總額為 {detail.product.required_total_twd === null ? "UNKNOWN" : formatTwd(detail.product.required_total_twd)}。UNKNOWN 不等於 NT$0。</span></div>
        <div className="status-row"><span className="status-badge"><b>券前價</b>{detail.product.before_coupon_price_twd === null ? "UNKNOWN" : formatTwd(detail.product.before_coupon_price_twd)}</span><span className="status-badge"><b>單件顯示</b>{view.primaryPrice === null ? "UNKNOWN" : formatTwd(view.primaryPrice)}</span><span className="status-badge"><b>最低數量</b>{detail.product.minimum_purchase_quantity}</span><span className="status-badge"><b>最低商品額</b>{view.minimumSpend === null ? "UNKNOWN" : formatTwd(view.minimumSpend)}</span><span className="status-badge warning"><b>含運必要總額</b>{detail.product.required_total_twd === null ? "UNKNOWN" : formatTwd(detail.product.required_total_twd)}</span></div>
        {detail.product.possible_coupon_price_twd !== null && !view.confirmed && <div className="coupon-warning" role="note"><b>可能券後價 {formatTwd(detail.product.possible_coupon_price_twd)} 不會作為主價。</b><span>{view.couponStatusLabel}；必須重新驗證領券、資格、效期與範圍。</span></div>}
        {!view.sourceUsable && <div className="unavailable-warning" role="note"><b>來源權限不可用，價格與歷史必須失效。</b><span>{detail.product.source_permission.state} · {detail.product.source_permission.reason}</span></div>}
        {view.primaryPrice === 0 && <div className="zero-warning" role="note"><b>已確認券後商品價為 NT$0，但不是零成本到手。</b><span>運費或必要費用未知，required_total_twd 維持 null。</span></div>}
        {truncation && <div className="coupon-warning" role="note"><b>歷史資料已裁切</b><span>{truncation}</span></div>}
        <div className="coupon-proof-grid"><article><span>精確身分</span><strong>{detail.product.series_identity.product_id}</strong><code>{detail.product.series_identity.sku_id} · {detail.product.series_identity.seller_id} · {detail.product.series_identity.condition} · {detail.product.series_identity.package_signature}</code></article><article><span>優惠券／資格</span><strong>{detail.product.coupon.coupon_id ?? "UNKNOWN"}</strong><code>{detail.product.coupon.eligibility_profile ?? "UNKNOWN"} · {detail.product.coupon.discount_scope}</code><code>{detail.product.coupon.evaluation_reasons.length ? detail.product.coupon.evaluation_reasons.join(" · ") : "EVIDENCE_CONFIRMED"}</code></article><article><span>來源權限／分類</span><strong>{detail.product.source_permission.reason}</strong><code>{detail.product.source_id ?? "UNKNOWN"} · {detail.data_classification}</code></article></div>
        <section className="history-contract-summary" aria-label="四組價格歷史摘要"><div><span>券前 raw</span><strong>{detail.history.before_coupon.length} 筆</strong></div><div><span>已確認券後 raw</span><strong>{detail.history.confirmed_after_coupon.length} 筆</strong></div><div><span>券前 daily</span><strong>{detail.history_quality.before_coupon.daily_representatives.length} 日</strong></div><div><span>已確認券後 daily</span><strong>{detail.history_quality.confirmed_after_coupon.daily_representatives.length} 日</strong></div><p>raw 保留來源觀測；daily 是依台北日界線彙整的每日代表價，兩者不互相補值。</p></section>
        <CouponHistoryChart before={detail.history.before_coupon} after={detail.history.confirmed_after_coupon}/>
        <div className="coupon-history-columns"><section className="history-list" aria-label="B10 券前商品價歷史" data-history-basis="before_coupon" data-history-granularity="raw"><div className="section-heading"><div><p className="eyebrow">RAW BEFORE COUPON</p><h3>券前商品價歷史（原始觀測）</h3></div><span>{detail.history_quality.before_coupon.raw_sample_count} 筆{detail.history_quality.before_coupon.truncated ? " · 已裁切" : ""}</span></div>{detail.history.before_coupon.length ? detail.history.before_coupon.map((item) => <div className="history-row coupon-history-row" data-observed-at={item.observed_at} data-price-twd={item.price_twd} key={`${item.observed_at}-${item.source_id}`}><time dateTime={item.observed_at}>{formatUtc(item.observed_at)}</time><strong>{formatTwd(item.price_twd)}</strong><code>{item.comparison_source}</code></div>) : <p className="empty-row">沒有券前 raw observation；不以零元補值。</p>}</section><section className="history-list" aria-label="B10 已確認券後商品價歷史" data-history-basis="confirmed_after_coupon" data-history-granularity="raw"><div className="section-heading"><div><p className="eyebrow">RAW CONFIRMED AFTER</p><h3>已確認券後商品價歷史（原始觀測）</h3></div><span>{detail.history_quality.confirmed_after_coupon.raw_sample_count} 筆{detail.history_quality.confirmed_after_coupon.truncated ? " · 已裁切" : ""}</span></div>{detail.history.confirmed_after_coupon.length ? detail.history.confirmed_after_coupon.map((item) => <div className="history-row coupon-history-row" data-observed-at={item.observed_at} data-price-twd={item.price_twd} key={`${item.observed_at}-${item.source_id}`}><time dateTime={item.observed_at}>{formatUtc(item.observed_at)}</time><strong>{formatTwd(item.price_twd)}</strong><code>{item.coupon_id}</code></div>) : <p className="empty-row">沒有已確認券後 raw observation；不套用可能、過期或不符資格的券價。</p>}</section></div>
        <div className="coupon-history-columns daily-history-columns"><section className="history-list" aria-label="B11 券前每日代表價" data-history-basis="before_coupon" data-history-granularity="daily"><div className="section-heading"><div><p className="eyebrow">DAILY BEFORE COUPON</p><h3>券前每日代表價</h3></div><span>{detail.history_quality.before_coupon.daily_representatives.length} 日</span></div>{detail.history_quality.before_coupon.daily_representatives.length ? detail.history_quality.before_coupon.daily_representatives.map((item) => <div className="history-row daily-history-row" data-taipei-date={item.taipei_date} data-representative-price-twd={item.representative_price_twd} data-sample-count={item.sample_count} key={item.taipei_date}><time dateTime={item.taipei_date}>{item.taipei_date}</time><strong>{formatTwd(item.representative_price_twd)}</strong><span>{item.sample_count} 個 raw 樣本</span></div>) : <p className="empty-row">沒有券前每日代表價；不以零元補值。</p>}</section><section className="history-list" aria-label="B11 已確認券後每日代表價" data-history-basis="confirmed_after_coupon" data-history-granularity="daily"><div className="section-heading"><div><p className="eyebrow">DAILY CONFIRMED AFTER</p><h3>已確認券後每日代表價</h3></div><span>{detail.history_quality.confirmed_after_coupon.daily_representatives.length} 日</span></div>{detail.history_quality.confirmed_after_coupon.daily_representatives.length ? detail.history_quality.confirmed_after_coupon.daily_representatives.map((item) => <div className="history-row daily-history-row" data-taipei-date={item.taipei_date} data-representative-price-twd={item.representative_price_twd} data-sample-count={item.sample_count} key={item.taipei_date}><time dateTime={item.taipei_date}>{item.taipei_date}</time><strong>{formatTwd(item.representative_price_twd)}</strong><span>{item.sample_count} 個 raw 樣本</span></div>) : <p className="empty-row">沒有已確認券後每日代表價；不以券前價補值。</p>}</section></div>
        <article className="affiliate-card coupon-cta"><p className="eyebrow">OUTBOUND DISABLED</p><h3>推薦／分潤連結</h3><button className="cta" disabled type="button">正式連結尚未核准</button><small>V4 價格整合不構成台灣官方分潤授權；不建立任何外連。</small></article></>}
      </section>
    </section>
  </main>;
}
