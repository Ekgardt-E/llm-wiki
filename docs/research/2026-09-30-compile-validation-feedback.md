# Compile retries carry validator feedback

Date: 2026-09-30. Installed Codex 0.159.2, configured gpt-6-luna/max.

The recovery run repeated the same immutable-evidence validation failure three
 times. `_CompileAttempt._record` printed the reason, but `_drafted` sent the
identical source prompt on each retry. A regression with a genuinely nonexistent
quotation reproduces this information loss: the second prompt lacks the actual
validator failure on the old implementation.

Primary sources reviewed today:
- [Pydantic AI retries](https://pydantic.dev/docs/ai/core-concepts/retries/):
  validation failures are returned to the model as correction feedback.
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
  schema compliance does not guarantee correct values; semantic validation remains necessary.
- [Anthropic troubleshooting](https://support.anthropic.com/en/articles/7996857-my-prompt-isn-t-giving-me-a-helpful-answer):
  follow-up feedback clarifies what a response needs to correct.

Decision: retain the existing retry policy and full immutable inputs, adding the
latest validation detail as explicitly labelled diagnostic data. The provider's
existing transport redaction still applies. Budget admission checks the enlarged
prompt before a call. The draft program version changes so old cached plans do
not stand in for the new contract. No dependency or runtime layout changes.

Alternatives: blind retries spend calls without useful feedback; weakening quote
matching would admit unsupported knowledge; replaying the entire invalid answer
would add unnecessary tokens and invalid claims. We use the existing validator
message, preserve all source bytes and never mark rejected work compiled.

The test proves feedback delivery and a subsequent valid plan, not that every
model mistake is now cured. A second test proves feedback participates in budget
admission. Existing provider failure, retry exhaustion, cache, claims and
transaction tests continue to apply. Live recovery must still complete before
claiming the backlog repaired.
