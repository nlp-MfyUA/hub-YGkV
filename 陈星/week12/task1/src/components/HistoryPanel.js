import React, { useEffect, useRef } from "react";
import { CloseIcon, ImageIcon } from "./icons";
import { getRiskMeta } from "../constants";
import { ResultView } from "./ResultPanel";

const pad = (value) => String(value).padStart(2, "0");

const formatShortTime = (iso) => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;

  if (date.toDateString() === now.toDateString()) return `今天 ${time}`;
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${time}`;
};

const formatFullTime = (iso) => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export const HistoryDetail = ({ item, onClose }) => {
  const closeRef = useRef(null);
  const meta = getRiskMeta(item.result.risk_level);
  const time = item.analyzed_at || item.created_at;

  useEffect(() => {
    const handleKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();

    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="history-modal"
        role="dialog"
        aria-modal="true"
        aria-label="识别记录详情"
      >
        <button
          ref={closeRef}
          type="button"
          className="modal-close"
          onClick={onClose}
          aria-label="关闭详情"
        >
          <CloseIcon size={20} />
        </button>

        <div className="history-modal__media">
          <figure className="polaroid" style={{ "--frame-color": meta.color }}>
            <div className="polaroid__photo">
              <img src={item.thumbnail} alt="历史识别的现场照片" />
            </div>
            <figcaption className="polaroid__caption">
              <div>
                <span>风险等级</span>
                <strong style={{ color: meta.color }}>{meta.label}</strong>
              </div>
              <time>{formatFullTime(time)}</time>
            </figcaption>
          </figure>
          <p className="history-modal__note">
            {item.result.scene_type || "未知场景"} · {item.provider_name}（{item.model}）
          </p>
        </div>

        <div className="history-modal__body">
          <ResultView analysis={item} />
        </div>
      </div>
    </div>
  );
};

const HistoryPanel = ({ items, onOpen, onClear }) => (
  <section className="history-panel">
    <div className="history-head">
      <div>
        <span className="eyebrow">检测档案</span>
        <h2>识别记录</h2>
        <p>最近识别过的现场照片，按风险等级标注，点击可查看完整研判结果。</p>
      </div>
      <div className="history-actions">
        <span className="history-count">共 {items.length} 条</span>
        {items.length > 0 && (
          <button type="button" className="ghost-btn" onClick={onClear}>
            清空记录
          </button>
        )}
      </div>
    </div>

    {items.length === 0 ? (
      <div className="history-empty">
        <div className="empty-frames" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <p>完成一次识别后，现场照片会以相框形式保存在这里，最多保留 12 条。</p>
      </div>
    ) : (
      <div className="history-grid">
        {items.map((item) => {
          const meta = getRiskMeta(item.result.risk_level);
          const time = item.analyzed_at || item.created_at;

          return (
            <button
              type="button"
              key={item.id}
              className="history-card"
              style={{ "--frame-color": meta.color, "--frame-soft": meta.soft }}
              onClick={() => onOpen(item)}
              title="查看识别详情"
            >
              <span className="history-frame">
                <img src={item.thumbnail} alt={`${meta.label}识别记录`} />
                <span className="photo-risk-badge">{meta.label}</span>
                <span className="photo-open-hint">
                  <ImageIcon size={14} />
                  查看详情
                </span>
              </span>
              <span className="history-meta">
                <span className="history-meta__top">
                  <strong style={{ color: meta.color }}>{meta.label}</strong>
                  <time>{formatShortTime(time)}</time>
                </span>
                <span className="history-summary">{item.result.summary}</span>
                <span className="history-model">
                  {item.provider_name} · {item.model}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    )}
  </section>
);

export default HistoryPanel;
