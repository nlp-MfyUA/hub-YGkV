import React, { useEffect, useMemo, useState } from "react";
import {
  AlertIcon,
  CheckCircleIcon,
  FlameIcon,
  ImageIcon,
  InfoIcon,
  MinusCircleIcon,
  ScanIcon,
  SparklesIcon,
  XCircleIcon,
} from "./icons";
import { ANALYSIS_STEPS, getRiskMeta } from "../constants";

const RiskLevelIcon = ({ level, size = 26 }) => {
  if (level === "high") return <FlameIcon size={size} />;
  if (level === "medium") return <AlertIcon size={size} />;
  if (level === "low") return <InfoIcon size={size} />;
  if (level === "none") return <CheckCircleIcon size={size} />;
  return <ImageIcon size={size} />;
};

const BoolIndicator = ({ label, value, danger = false }) => {
  const state = value === true ? "yes" : value === false ? "no" : "unknown";
  const Icon = state === "yes" ? CheckCircleIcon : state === "no" ? XCircleIcon : MinusCircleIcon;
  const text = state === "yes" ? "是" : state === "no" ? "否" : "未判断";

  return (
    <div className={`metric metric--${state} ${danger && state === "yes" ? "metric--danger" : ""}`}>
      <span className="metric__label">{label}</span>
      <span className="metric__value">
        <Icon size={17} />
        {text}
      </span>
    </div>
  );
};

const EmptyState = () => (
  <div className="result-empty">
    <div className="empty-visual">
      <div className="empty-scan">
        <span className="empty-scan__line" />
        <ImageIcon size={44} />
      </div>
      <span className="empty-badge">
        <SparklesIcon size={15} />
        多模态 AI 研判
      </span>
    </div>
    <h3>等待识别现场照片</h3>
    <p>拍照或上传楼道照片后，点击「开始智能识别」。</p>
    <ol className="flow-steps">
      <li>
        <span>1</span>
        采集楼道照片
      </li>
      <li>
        <span>2</span>
        识别堆物与起火因素
      </li>
      <li>
        <span>3</span>
        输出风险等级与建议
      </li>
    </ol>
  </div>
);

const AnalyzingState = ({ providerLabel }) => {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setStep((value) => (value + 1) % ANALYSIS_STEPS.length);
    }, 1800);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="result-loading">
      <div className="scan-box">
        <span className="scan-line" />
        <SparklesIcon size={40} />
      </div>
      <h3>正在分析画面</h3>
      <p className="loading-step">{ANALYSIS_STEPS[step]}</p>
      <div className="loading-dots">
        <span />
        <span />
        <span />
      </div>
      {providerLabel && <p className="loading-model">识别模型：{providerLabel}</p>}
    </div>
  );
};

export const ResultView = ({ analysis }) => {
  const [copied, setCopied] = useState(false);
  const { result } = analysis;
  const meta = getRiskMeta(result.risk_level);
  const confidence =
    typeof result.confidence === "number" ? `${Math.round(result.confidence * 100)}%` : "—";

  const time = useMemo(() => {
    if (!analysis.analyzed_at) return "";
    const date = new Date(analysis.analyzed_at);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }, [analysis.analyzed_at]);

  const copyText = async () => {
    const lines = [
      "【楼道消防安全隐患识别】",
      `风险等级：${result.risk_label}`,
      `场景类型：${result.scene_type}`,
      `风险概述：${result.summary}`,
    ];
    if (result.hazards?.length) {
      lines.push(`识别隐患：${result.hazards.map((item) => item.title).join("、")}`);
    }
    if (analysis.yolo_detections?.length) {
      lines.push(
        `YOLO 检测：${analysis.yolo_detections
          .map((item) => `${item.labelZh}×${item.count}`)
          .join("、")}`
      );
    }
    if (result.suggestions?.length) {
      lines.push("处置建议：");
      result.suggestions.forEach((item, index) => lines.push(`${index + 1}. ${item}`));
    }
    lines.push(`识别模型：${analysis.provider_name}（${analysis.model}）`);

    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="result-view">
      <div
        className="risk-banner"
        style={{ background: meta.soft, borderColor: meta.border }}
      >
        <span className="risk-icon" style={{ color: meta.color }}>
          <RiskLevelIcon level={result.risk_level} />
        </span>
        <div className="risk-headline">
          <span className="risk-caption">风险等级</span>
          <h3 style={{ color: meta.color }}>{result.risk_label}</h3>
          <p>{result.summary}</p>
        </div>
        <div className="confidence" style={{ color: meta.color }}>
          <strong>{confidence}</strong>
          <span>置信度</span>
        </div>
      </div>

      <div className="result-tags">
        <span className="tag">{result.scene_type || "未知场景"}</span>
        <span className="tag">{result.is_hallway ? "居民楼公共区域" : "非楼道场景"}</span>
        <span className="tag tag--model">
          {analysis.provider_name} · {analysis.model}
        </span>
        {typeof analysis.elapsed_ms === "number" && (
          <span className="tag">耗时 {(analysis.elapsed_ms / 1000).toFixed(1)} 秒</span>
        )}
        {analysis.yolo_detections?.length > 0 && (
          <span className="tag">YOLO 识别 {analysis.yolo_detections.length} 类物体</span>
        )}
        {time && <span className="tag">{time}</span>}
      </div>

      {result.is_hallway && (
        <div className="metrics">
          <BoolIndicator label="通道被明显占用" value={result.passage_blocked} danger />
          <BoolIndicator label="存在可燃堆积物" value={result.combustibles_present} danger />
          <BoolIndicator label="电动车 / 充电行为" value={result.charging_detected} danger />
        </div>
      )}

      {analysis.yolo_detections?.length > 0 && (
        <section className="result-section">
          <h4>
            <ScanIcon size={17} />
            本地 YOLO 检测
          </h4>
          <div className="result-detections">
            {analysis.yolo_detections.map((item) => (
              <span key={item.label || item.labelZh} className="result-detection">
                {item.labelZh}
                <b>×{item.count}</b>
                <em>{Math.round(item.maxScore * 100)}%</em>
              </span>
            ))}
          </div>
          <p className="result-detection-note">
            YOLO 仅负责定位通用物体，最终风险等级由 DeepSeek 结合画面判定。
          </p>
        </section>
      )}

      {result.hazards?.length > 0 && (
        <section className="result-section">
          <h4>
            <AlertIcon size={17} />
            识别到的隐患
          </h4>
          <ul className="hazard-list">
            {result.hazards.map((hazard, index) => {
              const severity = getRiskMeta(hazard.severity);
              return (
                <li key={`${hazard.title}-${index}`}>
                  <span
                    className="severity-dot"
                    style={{ background: severity.color, boxShadow: `0 0 0 4px ${severity.soft}` }}
                  />
                  <div>
                    <div className="hazard-title">
                      <strong>{hazard.title}</strong>
                      <span style={{ color: severity.color }}>{severity.label}</span>
                    </div>
                    {hazard.description && <p>{hazard.description}</p>}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {result.evidence?.length > 0 && (
        <section className="result-section">
          <h4>
            <ImageIcon size={17} />
            画面依据
          </h4>
          <ul className="evidence-list">
            {result.evidence.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </section>
      )}

      {result.suggestions?.length > 0 && (
        <section className="result-section">
          <h4>
            <CheckCircleIcon size={17} />
            处置建议
          </h4>
          <ol className="suggestion-list">
            {result.suggestions.map((item, index) => (
              <li key={index}>
                <span>{index + 1}</span>
                {item}
              </li>
            ))}
          </ol>
        </section>
      )}

      <div className="result-footer">
        <p>
          结果由 {analysis.provider_name}（{analysis.model}）生成，AI 识别仅供参考。如遇火情请立即拨打
          <strong> 119</strong>。
        </p>
        <button type="button" className="ghost-btn" onClick={copyText}>
          {copied ? "已复制结果" : "复制识别结果"}
        </button>
      </div>
    </div>
  );
};

const ResultPanel = ({ analysis, analyzing, error, providerLabel, onRetry }) => {
  const meta = analysis ? getRiskMeta(analysis.result.risk_level) : null;

  return (
    <section
      className={`card result-card ${meta ? "result-card--risk" : ""}`}
      style={
        meta
          ? { "--result-color": meta.color, "--result-soft": meta.soft }
          : undefined
      }
    >
      <div className="card-head">
        <div>
          <span className="eyebrow">第二步</span>
          <h2>风险研判结果</h2>
        </div>
        {analysis && !analyzing && (
          <span className="live-tag">
            <span className="status-dot status-dot--green" />
            已完成
          </span>
        )}
      </div>

      <div className="result-body">
        {analyzing ? (
          <AnalyzingState providerLabel={providerLabel} />
        ) : error ? (
          <div className="result-error">
            <span className="error-icon">
              <AlertIcon size={30} />
            </span>
            <h3>识别未能完成</h3>
            <p>{error}</p>
            <button type="button" className="secondary-btn" onClick={onRetry}>
              <SparklesIcon size={17} />
              重新识别
            </button>
          </div>
        ) : analysis ? (
          <ResultView analysis={analysis} />
        ) : (
          <EmptyState />
        )}
      </div>
    </section>
  );
};

export default ResultPanel;
