import { ArrowUp, ChatCircleText, Square, WarningCircle } from "@phosphor-icons/react";

export function InterviewComposer({ answer = "", setAnswer = () => {}, onKeyDown, onSubmit, onStop, isSubmitting, error, uploadControl, disabled = false, placeholder = "在这里回答当前问题…" }) {
  return (
    <div className="chat-composer-wrap">
      <div className="chat-composer-label"><ChatCircleText size={17} weight="duotone" /><span>{disabled ? "和 Agent 开始对话" : "你的回答"}</span>{!disabled && <small>{answer.length} 字</small>}</div>
      <div className={`chat-composer ${error ? "has-error" : ""} ${isSubmitting ? "is-busy" : ""}`} aria-busy={isSubmitting}>
        <textarea value={answer} onChange={(event) => setAnswer(event.target.value)} onKeyDown={onKeyDown} placeholder={placeholder} aria-label={disabled ? "和 Agent 对话" : "你的回答"} disabled={disabled} />
        <div className="chat-composer-footer">
          <div className="composer-tools" aria-label="聊天工具">{uploadControl}</div>
          <div className="composer-actions">
            {isSubmitting && <button className="stop-button composer-stop" type="button" onClick={onStop} aria-label="终止回答"><Square size={13} weight="fill" /> 停止回答</button>}
            <button className="primary-button composer-submit" type="button" onClick={onSubmit} disabled={disabled || isSubmitting} aria-label={isSubmitting ? "正在分析回答" : "提交回答"}>{isSubmitting ? "正在分析…" : "提交回答"} <ArrowUp size={18} weight="bold" /></button>
          </div>
        </div>
      </div>
      {error && <div className="form-error"><WarningCircle size={17} /> {error}</div>}
    </div>
  );
}
