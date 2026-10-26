import { useId, useState } from 'react';
import { QUESTION_MAX, validateQuestion } from '../../api/workflows.js';

const EXAMPLES = [
  'Which machines are down right now, and why?',
  'How much downtime did each machine have in the last 7 days?',
  'What were production output and rejection rate yesterday?',
  'List open high-priority maintenance requests.',
];

/** Natural-language question with local validation and example prompts. */
export function AskForm({ busy, canPropose, onAsk }) {
  const id = useId();
  const [question, setQuestion] = useState('');
  const [error, setError] = useState(null);

  const submit = (event) => {
    event.preventDefault();
    const problem = validateQuestion(question);
    setError(problem);
    if (!problem) onAsk(question.trim());
  };

  const examples = canPropose
    ? [...EXAMPLES, 'Prepare a high-priority maintenance request for machine <code>: spindle vibration is above normal.']
    : EXAMPLES;

  return (
    <form className="ask-form" aria-label="Ask the workflow assistant" onSubmit={submit} noValidate>
      <div className="field">
        <label htmlFor={id}>Your question</label>
        <textarea
          id={id}
          rows={3}
          maxLength={QUESTION_MAX + 200}
          value={question}
          disabled={busy}
          aria-invalid={error ? true : undefined}
          aria-describedby={`${id}-hint`}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <span id={`${id}-hint`} className="field__hint">
          {question.trim().length}/{QUESTION_MAX} characters. The assistant can only read plant data
          {canPropose ? ' and prepare maintenance requests for approval' : ''}; it cannot change records or control
          machines.
        </span>
        {error && (
          <span className="field__error" role="alert">
            {error}
          </span>
        )}
      </div>
      <div className="ask-form__actions">
        <div className="examples" role="group" aria-label="Example questions">
          {examples.map((example) => (
            <button
              key={example}
              type="button"
              className="button--ghost button--small"
              disabled={busy}
              onClick={() => {
                setQuestion(example);
                setError(null);
              }}
            >
              {example}
            </button>
          ))}
        </div>
        <button type="submit" disabled={busy}>
          {busy ? 'Working…' : 'Ask'}
        </button>
      </div>
    </form>
  );
}