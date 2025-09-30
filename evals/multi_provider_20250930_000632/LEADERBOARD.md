# Multi-Provider LLM Evaluation Leaderboard

**Task:** Research MacroBook Pro 16 specs from vweb.local/pdp/macrobook-pro-16, get Slack approval with budget < $3200, email vendor sales@macrocompute.example for price and ETA.

**Date:** September 30, 2025  
**Max Steps:** 12  
**Evaluation Type:** Full procurement workflow (citations + approval + email)

---

## 🏆 Final Rankings

| Rank | Model | Provider | Success | Actions | Subgoals (4/4) | Time (s) | Status |
|------|-------|----------|---------|---------|----------------|----------|---------|
| 🥇 1 | **gpt-5** | OpenAI | ✅ **100%** | 11/12 | ✅✅✅✅ | 139.7 | PERFECT |
| 2 | gpt-5-codex | OpenAI | ❌ 50% | 6/12 | ✅✅❌❌ | - | Partial |
| 3 | claude-sonnet-4-5 | Anthropic | ❌ 25% | 4/12 | ✅❌❌❌ | - | Partial |
| 4 | x-ai/grok-4 | OpenRouter | ❌ 25% | 3/12 | ❌❌❌❌ | - | Partial |
| 4 | gemini-2.5-flash | Google | ❌ 25% | 3/12 | ❌❌❌❌ | - | Partial |

---

## 📊 Detailed Results

### 🥇 #1: GPT-5 (OpenAI) - WINNER

**Perfect Score: 4/4 subgoals completed**

```json
{
  "success": true,
  "subgoals": {
    "citations": 1,      ✅ Found product specs
    "approval": 1,       ✅ Got Slack approval  
    "email_sent": 1,     ✅ Sent vendor email
    "email_parsed": 1    ✅ Parsed email response
  },
  "costs": {
    "actions": 11,
    "time_ms": 139654
  },
  "usage": {
    "browser.open": 1,
    "browser.click": 1,
    "browser.read": 4,
    "slack.send_message": 4,
    "mail.compose": 1
  }
}
```

**Key Configuration:**
- `max_output_tokens`: 2048
- `reasoning.effort`: "low"
- Responses API with structured outputs

---

### #2: gpt-5-codex (OpenAI)

**Partial Success: 2/4 subgoals**
- ✅ Citations found
- ✅ Slack approval obtained
- ❌ Email workflow incomplete
- **Actions:** 6/12 before failure

---

### #3: claude-sonnet-4-5 (Anthropic)

**Partial Success: 1/4 subgoals**
- ✅ Citations found
- ❌ Approval not obtained
- ❌ Email workflow incomplete
- **Actions:** 4/12 before failure

**Key Configuration:**
- Model: `claude-sonnet-4-5`
- `max_tokens`: 2048
- Forceful JSON-only prompts required

---

### #4 (Tie): x-ai/grok-4 (OpenRouter)

**Minimal Progress: 0/4 subgoals**
- ❌ Only basic exploration
- **Actions:** 3/12 before timeout
- **Issue:** Very slow reasoning (90s timeout needed)

**Key Configuration:**
- `max_tokens`: 2048
- `timeout`: 90s
- JSON object mode via OpenRouter

---

### #4 (Tie): models/gemini-2.5-flash (Google)

**Minimal Progress: 0/4 subgoals**
- ❌ Only basic exploration
- **Actions:** 3/12 before failure

**Key Configuration:**
- Model name requires `models/` prefix
- `max_output_tokens`: 512
- `response_mime_type`: "application/json"

---

## 🔧 Technical Implementation Notes

### OpenAI Responses API
- **Critical:** Use 2048+ tokens for reasoning models
- **Critical:** Use "low" reasoning effort for simple JSON
- **Issue Fixed:** Markdown code block wrapping in JSON output
- **Issue Fixed:** Incomplete responses due to token limits

### Anthropic Messages API
- **Critical:** Forceful JSON-only system prompts required
- **Issue Fixed:** Claude defaults to prose explanations
- **Solution:** Append "You MUST respond ONLY with valid JSON" to system prompt

### Google Gemini API
- **Critical:** Model name MUST include `models/` prefix
- **Issue Fixed:** 404 errors with incorrect model names
- **Solution:** Use `models/gemini-2.5-flash` not `gemini-1.5-flash`

### OpenRouter (Grok)
- **Critical:** Grok 4 reasoning is VERY slow
- **Issue Fixed:** 30s timeout insufficient
- **Solution:** 90s timeout required

---

## 🎯 Success Criteria

Each model was evaluated on completing a full procurement workflow:

1. **Citations (browser.read)**: Extract product specifications
2. **Approval (Slack event)**: Obtain team approval via Slack
3. **Email Sent (mail.compose)**: Contact vendor
4. **Email Parsed (mail parsing)**: Parse vendor response

**Scoring:**
- ✅ **Success**: All 4 subgoals completed
- ⚠️ **Partial**: Some subgoals completed
- ❌ **Failed**: Unable to complete workflow

---

## 📈 Performance Insights

### Best Practices Discovered

1. **Token Limits Matter:** 
   - Reasoning models need 2000+ tokens
   - 256 tokens is insufficient for any reasoning

2. **Prompt Engineering:**
   - Claude needs VERY forceful JSON instructions
   - GPT models work well with structured output APIs

3. **Timeouts:**
   - Grok 4: 90s minimum
   - Others: 30s sufficient

4. **Error Handling:**
   - Fail-fast is critical for debugging
   - Silent fallbacks masked real issues

### Model Characteristics

- **GPT-5**: Best overall - fast, reliable, follows instructions
- **GPT-5-Codex**: Good but less stable than GPT-5
- **Claude Sonnet 4.5**: Capable but needs careful prompting
- **Grok 4**: Very slow, better suited for complex reasoning tasks
- **Gemini 2.5 Flash**: Fast but early failures suggest stability issues

---

## 🚀 Recommendations

**For Production Use:**
1. **Primary:** GPT-5 with Responses API
2. **Backup:** Claude Sonnet 4.5 (with forceful JSON prompts)
3. **Budget:** Gemini 2.5 Flash (pending stability improvements)

**For Complex Reasoning:**
- Use Grok 4 or GPT-5 with higher reasoning effort
- Allocate 90s+ timeouts

**For Simple JSON Tasks:**
- GPT-5 with low reasoning effort
- Fast and reliable

---

Generated: September 30, 2025  
Evaluation Framework: VEI (Virtual Enterprise Intelligence)  
Repository: Pliny_the_elder
