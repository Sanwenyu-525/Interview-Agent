import { CheckCircle, Sparkle, WarningCircle } from "@phosphor-icons/react";
import { TokenUsageCircle } from "./TokenUsageCircle";

export function InterviewThread({ session, history = [], isSubmitting, pendingAnswer, streamingReply, streamingEval, streamingStatus, streamingSteps = [], tokenUsage, messageListRef, directionLabel, processStepsForRecord }) {
  return (
    <div className="agent-thread">
      <div className="agent-thread-heading"><span className="agent-avatar"><Sparkle size={17} weight="duotone" /></span><span><strong>Interview Agent</strong><small>正在围绕 {session.topic || "当前项目"} 提问</small></span><span className="thread-state">{session.questionProgressLabel}</span></div>
      <div className="agent-message-list" ref={messageListRef}>
        {history.map((record, index) => (
          <details className="history-pair history-collapsed" key={`${record.question || "question"}-${index}`}>
            <summary className="history-summary"><span className="history-summary-index">已完成 {index + 1}</span><span className="history-summary-question">{record.question || "历史问题"}</span>{record.evaluation?.score !== undefined && <strong>评分 {record.evaluation.score} / 100</strong>}</summary>
            <div className="history-pair-body">
              <article className="agent-message agent-message-agent history-message">
                <span className="agent-avatar"><Sparkle size={17} weight="duotone" /></span>
                <div className="agent-message-body"><span className="message-meta">面试官 · 第 {index + 1} 题</span><div className="message-bubble history-question-bubble"><p>{record.question || "历史问题"}</p></div>{record.analysis && <details className="process-details"><summary><span>出题思路</span></summary><p className="analysis-content">{record.analysis}</p></details>}</div>
              </article>
              <article className="agent-message agent-message-user history-message">
                <span className="agent-avatar user-avatar">你</span>
                <div className="agent-message-body"><span className="message-meta">你的回答 · 已提交</span><div className="message-bubble user-message-bubble"><p>{record.answer || "未填写回答"}</p>{record.evaluation?.score !== undefined && <small className="message-score">评分 {record.evaluation.score} / 100</small>}</div></div>
              </article>
              {record.evaluation && <details className="history-evaluation">
                <summary><span>评价与处理过程</span><strong>评分 {record.evaluation.score ?? "—"} / 100</strong></summary>
                <div className="history-evaluation-body">
                  {record.evaluation.analysis && <details className="process-details"><summary><span>思考过程</span></summary><p className="analysis-content">{record.evaluation.analysis}</p></details>}
                  <details className="process-details"><summary>处理过程</summary><ol className="process-step-list">{processStepsForRecord(record).map((step, stepIndex) => <li key={`${step}-${stepIndex}`}>{step}</li>)}</ol></details>
                  {record.evaluation.feedback && <p className="history-feedback">{record.evaluation.feedback}</p>}
                  {(record.evaluation.strengths || []).map((strength) => <div className="history-feedback-point is-strength" key={`strength-${strength}`}><CheckCircle size={15} weight="fill" /><span>{strength}</span></div>)}
                  {(record.evaluation.weaknesses || []).map((weakness) => <div className="history-feedback-point is-weakness" key={`weakness-${weakness}`}><WarningCircle size={15} weight="fill" /><span>{weakness}</span></div>)}
                </div>
              </details>}
              {record.evaluation?.reference_answer && <article className="agent-message agent-message-agent history-message reference-answer-message">
                <span className="agent-avatar"><Sparkle size={17} weight="duotone" /></span>
                <div className="agent-message-body"><span className="message-meta">面试官 · 参考回答</span><div className="message-bubble"><p>{record.evaluation.reference_answer}</p></div></div>
              </article>}
            </div>
          </details>
        ))}
        <article className="agent-message agent-message-agent current-question-message">
          <span className="agent-avatar"><Sparkle size={17} weight="duotone" /></span>
          <div className="agent-message-body"><span className="message-meta">面试官 · 当前问题</span><div className="message-bubble current-question-bubble"><h1>{session.question || "暂无问题"}</h1>{session.context && <p>{session.context}</p>}{session.instruction && <p>{session.instruction}</p>}</div>{session.questionAnalysis && <details className="process-details"><summary><span>出题思路</span></summary><p className="analysis-content">{session.questionAnalysis}</p></details>}</div>
        </article>
        {isSubmitting && <>
          <article className="agent-message agent-message-user history-message">
            <span className="agent-avatar user-avatar">你</span>
            <div className="agent-message-body"><span className="message-meta">你的回答 · 已提交</span><div className="message-bubble user-message-bubble"><p>{pendingAnswer || "未填写回答"}</p></div></div>
          </article>
          <article className="agent-message agent-message-agent streaming-message" aria-live="polite">
            <span className="agent-avatar"><Sparkle size={17} weight="duotone" /></span>
            <div className="agent-message-body"><div className="streaming-heading"><span className="message-meta">面试官 · {streamingReply ? "参考回答 · 流式输出" : streamingEval ? "思考与评价 · 实时输出" : streamingStatus || "处理中"}</span>{tokenUsage && <TokenUsageCircle usage={tokenUsage} />}</div><div className="message-bubble"><p className={streamingEval && !streamingReply ? "eval-stream-text" : ""}>{streamingReply || streamingEval || streamingStatus || "正在评价回答"}<span className="streaming-cursor" aria-hidden="true" /></p></div>{streamingSteps.length > 0 && <details className="process-details" open><summary><span>处理过程</span><small>{streamingStatus || "正在处理"}</small></summary><ol className="process-step-list">{streamingSteps.map((step, index) => <li key={`${step}-${index}`}>{step}</li>)}</ol></details>}</div>
          </article>
        </>}
        {history.length > 0 && <div className="agent-system-message"><CheckCircle size={18} /><span><strong>已完成 {history.length} 次回答</strong><small>下一步：{directionLabel(session.nextDirection)}</small></span></div>}
      </div>
    </div>
  );
}
