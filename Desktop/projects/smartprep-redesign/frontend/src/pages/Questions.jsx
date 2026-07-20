import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../services/api';
import EvaluationCard from '../components/EvaluationCard';
import VoiceRecorder  from '../components/VoiceRecorder';
import Icon from '../components/Icon';
import styles from './Questions.module.css';

const MODE_PERSONA = {
  behavioral: {
    name: 'Sarah Chen',
    role: 'Senior Hiring Manager',
    icon: 'handshake',
    prompt: 'Use the STAR method. Be specific and quantify your impact.',
  },
  coding: {
    name: 'Alex Patel',
    role: 'Staff Engineer',
    icon: 'code',
    prompt: 'Walk me through your approach before coding. Discuss time and space complexity.',
  },
  system_design: {
    name: 'Jordan Kim',
    role: 'Staff Infrastructure Engineer',
    icon: 'layers',
    prompt: 'Scope requirements first. Articulate trade-offs clearly.',
  },
};

function formatTime(secs) {
  const m = Math.floor(secs / 60).toString().padStart(2, '0');
  const s = (secs % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export default function Questions({
  sessionId, questions, jobRole, keyRequirements,
  tier, mode, timerSeconds, onComplete, onRestart,
}) {
  const [activeQ,              setActiveQ]              = useState(null);
  const [answers,              setAnswers]              = useState({});
  const [evaluations,          setEvaluations]          = useState({});
  const [loading,              setLoading]              = useState({});
  const [errors,               setErrors]               = useState({});
  const [speechMetrics,        setSpeechMetrics]        = useState({});
  const [agentActions,         setAgentActions]         = useState({});
  const [agentLoading,         setAgentLoading]         = useState({});
  const [followUpAnswers,      setFollowUpAnswers]      = useState({});
  const [followUpEvaluations,  setFollowUpEvaluations]  = useState({});
  const [followUpLoading,      setFollowUpLoading]      = useState({});
  const [followUpErrors,       setFollowUpErrors]       = useState({});
  const [timeLeft,        setTimeLeft]        = useState(timerSeconds);
  const [timerWarning,    setTimerWarning]    = useState(false);
  const [timerCritical,   setTimerCritical]   = useState(false);
  const [sessionHistory,  setSessionHistory]  = useState([]);
  const timerRef    = useRef(null);
  const submittedRef = useRef(false);

  const completedCount = Object.keys(evaluations).length;
  const avgScore = completedCount > 0
    ? (Object.values(evaluations).reduce((s, e) => s + e.score, 0) / completedCount).toFixed(1)
    : null;

  const buildDebriefPayload = useCallback((evals) =>
    Object.entries(evals).map(([id, ev]) => {
      const q = questions.find(q => q.id === parseInt(id));
      return {
        question_id: parseInt(id),
        question:    q?.question  || '',
        category:    q?.category  || 'General',
        difficulty:  q?.difficulty || 'Medium',
        score:       ev.score,
        rubric_scores: ev.rubric_scores || null,
      };
    })
  , [questions]);

  const finalizeSession = useCallback(async (evals, timeUsed) => {
    if (submittedRef.current) return;
    submittedRef.current = true;
    const results = buildDebriefPayload(evals);
    let report = null;
    try {
      report = await api.sessionDebrief({ session_id: sessionId, mode, tier, results, time_used_seconds: timeUsed });
    } catch (e) {
      console.warn('Debrief failed, proceeding without report:', e);
    }
    onComplete(results, report);
  }, [sessionId, mode, tier, buildDebriefPayload, onComplete]);

  useEffect(() => {
    timerRef.current = setInterval(() => {
      setTimeLeft(prev => {
        if (prev <= 1) {
          clearInterval(timerRef.current);
          setEvaluations(evals => { finalizeSession(evals, timerSeconds); return evals; });
          return 0;
        }
        const next = prev - 1;
        setTimerWarning(next <= timerSeconds * 0.2);
        setTimerCritical(next <= timerSeconds * 0.1);
        return next;
      });
    }, 1000);
    return () => clearInterval(timerRef.current);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleEvaluate = async (q) => {
    const answer = answers[q.id];
    if (!answer?.trim()) return;
    setLoading(prev  => ({ ...prev, [q.id]: true  }));
    setErrors(prev   => ({ ...prev, [q.id]: ''    }));
    try {
      const result = await api.evaluateAnswer({
        session_id:    sessionId,
        question:      q.question,
        user_answer:   answer,
        category:      q.category,
        mode,
        speech_metrics: speechMetrics[q.id] || null,
      });
      const newEvals = { ...evaluations, [q.id]: result };
      setEvaluations(newEvals);
      setActiveQ(null);
      const turn = { question: q.question, score: result.score, answer };
      setSessionHistory(h => [...h, turn]);

      setAgentLoading(prev => ({ ...prev, [q.id]: true }));
      try {
        const agentResult = await api.agentNextMove({
          session_id: sessionId, question: q.question,
          user_answer: answer, evaluation: result, history: sessionHistory, mode,
        });
        setAgentActions(prev => ({ ...prev, [q.id]: agentResult }));
      } catch (e) {
        console.warn('Agent next-move failed (non-fatal):', e);
      } finally {
        setAgentLoading(prev => ({ ...prev, [q.id]: false }));
      }
    } catch (e) {
      setErrors(prev => ({ ...prev, [q.id]: e?.message || 'Evaluation failed. Please try again.' }));
    } finally {
      setLoading(prev => ({ ...prev, [q.id]: false }));
    }
  };

  const handleFollowUpEvaluate = async (qId, questionText) => {
    const answer = followUpAnswers[qId];
    if (!answer?.trim()) return;
    setFollowUpLoading(prev => ({ ...prev, [qId]: true  }));
    setFollowUpErrors(prev  => ({ ...prev, [qId]: ''    }));
    try {
      const result = await api.evaluateAnswer({
        session_id:  sessionId,
        question:    questionText,
        user_answer: answer,
        category:    'Follow-up',
        mode,
        speech_metrics: null,
      });
      setFollowUpEvaluations(prev => ({ ...prev, [qId]: result }));
    } catch (e) {
      setFollowUpErrors(prev => ({ ...prev, [qId]: e?.message || 'Evaluation failed. Please try again.' }));
    } finally {
      setFollowUpLoading(prev => ({ ...prev, [qId]: false }));
    }
  };

  const handleCompleteSession = () => {
    clearInterval(timerRef.current);
    finalizeSession(evaluations, timerSeconds - timeLeft);
  };

  const persona     = MODE_PERSONA[mode] || MODE_PERSONA.behavioral;
  const timerColor  = timerCritical ? 'var(--danger)' : timerWarning ? 'var(--warn)' : 'var(--text-2)';
  const timerBorder = timerCritical ? 'var(--danger)' : timerWarning ? 'var(--warn)' : 'var(--border)';

  return (
    <div className={styles.container}>

      {/* ── Session header ───────────────────────────────────── */}
      <div className={`${styles.sessionHeader} fade-up`}>
        <div className={styles.headerLeft}>
          <h2 className={styles.title}>Interview session</h2>
          <p className={styles.meta}>
            <span className={styles.tierBadge} data-tier={tier}>{tier}</span>
            <span className={styles.dot}>·</span>
            {jobRole}
            {avgScore && <><span className={styles.dot}>·</span>avg <strong>{avgScore}</strong>/10</>}
          </p>
        </div>
        <div className={styles.headerRight}>
          <div className={styles.timer} style={{ color: timerColor, borderColor: timerBorder }}>
            <Icon name="clock" size={14} />
            <span className={styles.timerVal}>{formatTime(timeLeft)}</span>
          </div>
          <div className={styles.progressWrap}>
            <span className={styles.progressText}>{completedCount}<span className={styles.progressOf}>/{questions.length}</span></span>
            <div className={styles.progressBar}>
              <div
                className={styles.progressFill}
                style={{ width: `${(completedCount / questions.length) * 100}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* ── Persona card ─────────────────────────────────────── */}
      <div className={`${styles.personaCard} fade-up-1`}>
        <div className={styles.personaIconWrap}>
          <Icon name={persona.icon} size={18} />
        </div>
        <div className={styles.personaInfo}>
          <span className={styles.personaName}>{persona.name}</span>
          <span className={styles.personaRole}>{persona.role}</span>
        </div>
        <p className={styles.personaPrompt}>{persona.prompt}</p>
      </div>

      {/* ── Key requirements ─────────────────────────────────── */}
      {keyRequirements.length > 0 && (
        <div className={`${styles.reqsBox} fade-up-1`}>
          <span className={styles.reqsLabel}>Key requirements</span>
          <div className={styles.reqs}>
            {keyRequirements.map((r, i) => (
              <span key={i} className={styles.req}>
                <Icon name="checkCircle" size={12} />{r}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Question list ─────────────────────────────────────── */}
      <div className={styles.questionList}>
        {questions.map((q, i) => {
          const isOpen      = activeQ === q.id;
          const hasEval     = !!evaluations[q.id];
          const isLoading   = loading[q.id];
          const agentAction = agentActions[q.id];
          const isAgentLoad = agentLoading[q.id];

          return (
            <div
              key={q.id}
              id={`question-${q.id}`}
              className={`${styles.card} ${isOpen ? styles.cardOpen : ''} ${hasEval ? styles.cardDone : ''} fade-up`}
              style={{ animationDelay: `${i * 0.05}s` }}
            >
              {/* Card header — always visible */}
              <div className={styles.cardHeader} onClick={() => setActiveQ(isOpen ? null : q.id)}>
                <div className={`${styles.num} ${hasEval ? styles.numDone : ''}`}>
                  {hasEval ? <Icon name="checkCircle" size={14} /> : <span>{i + 1}</span>}
                </div>
                <div className={styles.cardMeta}>
                  <span className={styles.catBadge}>{q.category}</span>
                  <span className={`${styles.diff} ${styles['diff_' + q.difficulty?.toLowerCase()]}`}>
                    {q.difficulty}
                  </span>
                  {hasEval && (
                    <span className={styles.evalScore} style={{
                      color: evaluations[q.id].score >= 7 ? 'var(--success)' : evaluations[q.id].score >= 5 ? 'var(--warn)' : 'var(--danger)'
                    }}>
                      {evaluations[q.id].score.toFixed(1)}/10
                    </span>
                  )}
                  {hasEval && evaluations[q.id].low_confidence_flag && (
                    <span className={styles.lowConfBadge} title="Low-confidence grading">
                      <Icon name="exclamationTriangle" size={11} /> Low confidence
                    </span>
                  )}
                </div>
                <Icon
                  name={isOpen ? 'chevronUp' : 'chevronDown'}
                  size={16}
                  style={{ color: 'var(--text-3)', flexShrink: 0 }}
                />
              </div>

              {/* Question text — always visible */}
              <p className={styles.questionText} onClick={() => setActiveQ(isOpen ? null : q.id)}>
                {q.question}
              </p>

              {/* Expanded panel */}
              {isOpen && (
                <div className={styles.panel}>
                  {q.rationale && (
                    <div className={styles.rationale}>
                      <span className={styles.rationaleLabel}>
                        <Icon name="informationCircle" size={13} /> Why this question
                      </span>
                      <span className={styles.rationaleText}>{q.rationale}</span>
                    </div>
                  )}

                  {!hasEval ? (
                    <>
                      <VoiceRecorder
                        onTranscript={(text) => setAnswers(prev => ({ ...prev, [q.id]: (prev[q.id] || '') + text }))}
                        onMetrics={(m) => setSpeechMetrics(prev => ({ ...prev, [q.id]: m }))}
                      />
                      <textarea
                        id={`answer-${q.id}`}
                        className={styles.answerInput}
                        rows={5}
                        placeholder="Write your answer here — be specific and use examples from your experience."
                        value={answers[q.id] || ''}
                        onChange={(e) => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))}
                      />
                      {errors[q.id] && (
                        <div className={styles.errorMsg}>
                          <Icon name="exclamationTriangle" size={14} /> {errors[q.id]}
                        </div>
                      )}
                      <button
                        id={`submit-answer-${q.id}`}
                        className={styles.evalBtn}
                        disabled={!answers[q.id]?.trim() || isLoading}
                        onClick={() => handleEvaluate(q)}
                      >
                        {isLoading
                          ? <><span className="spinner" /> Evaluating…</>
                          : <><Icon name="send" size={15} /> Submit answer</>
                        }
                      </button>
                    </>
                  ) : (
                    <>
                      <EvaluationCard evaluation={evaluations[q.id]} />

                      {isAgentLoad && (
                        <div className={styles.agentLoading}>
                          <span className="spinner" />
                          <span>Interviewer is deciding next move…</span>
                        </div>
                      )}

                      {agentAction && !isAgentLoad && agentAction.action !== 'next_question' && (
                        <div className={styles.agentCard} data-action={agentAction.action}>
                          <div className={styles.agentHeader}>
                            <Icon name="brain" size={16} style={{ color: 'var(--accent)' }} />
                            <span className={styles.agentActionLabel}>
                              {agentAction.action === 'probe_deeper' && 'Probing deeper'}
                              {agentAction.action === 'pivot'        && 'Pivoting topic'}
                              {agentAction.action === 'escalate'     && 'Escalating difficulty'}
                            </span>
                            <span className={styles.agentRationale}>{agentAction.rationale}</span>
                          </div>
                          {(agentAction.follow_up_question || agentAction.escalated_question) && (() => {
                            const fuQ = agentAction.follow_up_question || agentAction.escalated_question;
                            const fuEval = followUpEvaluations[q.id];
                            const fuLoad = followUpLoading[q.id];
                            const fuErr  = followUpErrors[q.id];
                            const scoreColor = fuEval
                              ? fuEval.score >= 7 ? 'var(--success)' : fuEval.score >= 5 ? 'var(--warn)' : 'var(--danger)'
                              : null;
                            return (
                              <div className={styles.agentQuestion}>
                                <p className={styles.agentQuestionText}>{fuQ}</p>
                                {!fuEval ? (
                                  <>
                                    <textarea
                                      id={`follow-up-${q.id}`}
                                      className={styles.answerInput}
                                      rows={4}
                                      placeholder="Answer the follow-up…"
                                      value={followUpAnswers[q.id] || ''}
                                      onChange={(e) => setFollowUpAnswers(prev => ({ ...prev, [q.id]: e.target.value }))}
                                    />
                                    {fuErr && (
                                      <div className={styles.errorMsg}>
                                        <Icon name="exclamationTriangle" size={14} /> {fuErr}
                                      </div>
                                    )}
                                    <button
                                      id={`submit-followup-${q.id}`}
                                      className={styles.evalBtn}
                                      disabled={!followUpAnswers[q.id]?.trim() || fuLoad}
                                      onClick={() => handleFollowUpEvaluate(q.id, fuQ)}
                                    >
                                      {fuLoad
                                        ? <><span className="spinner" /> Evaluating…</>
                                        : <><Icon name="send" size={15} /> Submit follow-up</>
                                      }
                                    </button>
                                  </>
                                ) : (
                                  <div className={styles.followUpResult}>
                                    <div className={styles.followUpScore} style={{ color: scoreColor }}>
                                      <Icon name="checkCircle" size={16} />
                                      Follow-up score: <strong>{fuEval.score.toFixed(1)}/10</strong>
                                      <span className={styles.followUpGrade} style={{ color: scoreColor }}>{fuEval.grade}</span>
                                    </div>
                                    {fuEval.detailed_feedback && (
                                      <p className={styles.followUpFeedback}>{fuEval.detailed_feedback}</p>
                                    )}
                                  </div>
                                )}
                              </div>
                            );
                          })()}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── All done banner ───────────────────────────────────── */}
      {completedCount === questions.length && (
        <div className={`${styles.summary} fade-up`}>
          <div className={styles.summaryIconWrap}>
            <Icon name="star" size={24} />
          </div>
          <h3 className={styles.summaryTitle}>All {questions.length} questions answered</h3>
          <p className={styles.summaryText}>
            Average score: <strong>{avgScore}/10</strong>. Ready to see your full debrief report?
          </p>
          <div className={styles.summaryActions}>
            <button id="view-debrief-btn" className={styles.debriefBtn} onClick={handleCompleteSession}>
              View debrief report <Icon name="arrowRight" size={16} />
            </button>
            <button className={styles.restartLink} onClick={onRestart}>Start over</button>
          </div>
        </div>
      )}
    </div>
  );
}
