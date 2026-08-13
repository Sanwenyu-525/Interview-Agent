import { ArrowUpRight, CheckCircle, GearSix, WarningCircle, X } from "@phosphor-icons/react";
import { TokenUsageCircle } from "./TokenUsageCircle";

export function EvaluationSummary({ evaluation, tokenUsage, nextDirection, capabilityHints = [], isRubricOpen, onToggleRubric, onCloseRubric, onOpenProjectKnowledge, directionLabel }) {
  return (
    <>
      <section className="evaluation-section">
        <div className="evaluation-title"><h2>当前评估</h2><span>（提交后更新）</span></div>
        {evaluation ? <div className="score-card"><div className="score-topline"><span>综合评分</span><span className="score-direction">{directionLabel(nextDirection)}</span></div><strong className="score-number">{evaluation.score ?? "—"}<small> / 100</small></strong>{tokenUsage && <div className="evaluation-token-row"><TokenUsageCircle usage={tokenUsage} /><span>本次回答 Token 用量</span></div>}{(evaluation.strengths || []).map((strength) => <div className="feedback-row strength" key={strength}><CheckCircle size={18} weight="fill" /><span>{strength}</span></div>)}{(evaluation.weaknesses || []).map((weakness) => <div className="feedback-row weakness" key={weakness}><WarningCircle size={18} weight="fill" /><span>{weakness}</span></div>)}{evaluation.feedback && <p>{evaluation.feedback}</p>}{evaluation.analysis && <details className="process-details score-analysis"><summary><span>思考过程</span></summary><p className="analysis-content">{evaluation.analysis}</p></details>}</div> : <div className="evaluation-card"><div className="evaluation-empty-state"><strong>暂无评价</strong><p>提交当前问题的回答后，这里会显示综合评分、优点与待改进点。</p></div></div>}
        {capabilityHints.length > 0 && <div className="capability-hints"><strong>能力提示</strong>{capabilityHints.map((hint) => <span key={hint}>{hint}</span>)}</div>}
        <p className="evaluation-note">评价和能力提示来自后端 evaluation。</p>
      </section>
      <div className="evidence-footer"><button className="quiet-button" type="button" aria-expanded={isRubricOpen} aria-controls="evaluation-rubric" onClick={onToggleRubric}><GearSix size={18} /> 评分标准</button><button className="quiet-button" type="button" onClick={onOpenProjectKnowledge}><ArrowUpRight size={18} /> 查看项目知识</button></div>
      {isRubricOpen && <section id="evaluation-rubric" className="rubric-panel" aria-label="评分标准"><div className="rubric-heading"><div><p className="view-kicker">REVIEW RUBRIC</p><h3>评分标准</h3></div><button className="icon-button" type="button" aria-label="关闭评分标准" onClick={onCloseRubric}><X size={17} /></button></div><div className="rubric-list"><div><strong>0–59 分</strong><span>基础澄清</span><small>补充项目事实、基础概念和术语。</small></div><div><strong>60–79 分</strong><span>深入实现</span><small>围绕调用链、实现细节和证据继续追问。</small></div><div><strong>80–100 分</strong><span>架构权衡</span><small>进入容量、稳定性、风险和系统演进讨论。</small></div></div></section>}
    </>
  );
}
