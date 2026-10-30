import React from "react";
import { AlertIcon, CheckCircleIcon, FlameIcon, ImageIcon, InfoIcon } from "./icons";
import { RISK_GUIDE, RISK_META } from "../constants";

const GuideIcon = ({ level }) => {
  if (level === "high") return <FlameIcon size={20} />;
  if (level === "medium") return <AlertIcon size={20} />;
  if (level === "low") return <InfoIcon size={20} />;
  if (level === "none") return <CheckCircleIcon size={20} />;
  return <ImageIcon size={20} />;
};

const RiskGuide = () => (
  <section className="risk-guide">
    <div className="risk-guide-head">
      <div>
        <span className="eyebrow">判定依据</span>
        <h2>楼道消防隐患分级标准</h2>
      </div>
      <p>系统综合楼道堆物、可燃物与起火因素判定，取最高风险等级。</p>
    </div>

    <div className="risk-guide-grid">
      {RISK_GUIDE.map((item) => {
        const meta = RISK_META[item.level];
        return (
          <article
            key={item.level}
            className="risk-guide-item"
            style={{ "--risk-color": meta.color, "--risk-soft": meta.soft }}
          >
            <span className="guide-icon" style={{ color: meta.color, background: meta.soft }}>
              <GuideIcon level={item.level} />
            </span>
            <div>
              <h3 style={{ color: meta.color }}>{item.title}</h3>
              <p>{item.text}</p>
            </div>
          </article>
        );
      })}
    </div>
  </section>
);

export default RiskGuide;
