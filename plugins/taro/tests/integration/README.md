# Integration Tests: Real LLM Communication

These tests validate end-to-end language parameter flow with **real LLM API communication**.

## Purpose

The unit tests mock the LLM adapter. These integration tests use the **actual LLM API** with real credentials from `vbwd-backend/plugins/config.json` to validate:

1. ✅ Language parameter flows through entire system
2. ✅ Real LLM receives language instruction in prompt
3. ✅ LLM respects language instruction
4. ✅ Responses are generated in the requested language

## Running the Tests

### Prerequisites
- Valid LLM API credentials in `vbwd-backend/plugins/config.json`
- LLM API endpoint must be accessible
- Database running (`make up`)

### Run All Integration Tests
```bash
cd vbwd-backend
pytest plugins/taro/tests/integration/test_real_llm_language.py -v -s
```

The `-s` flag shows print output (useful to see actual LLM responses).

### Run Specific Test
```bash
pytest plugins/taro/tests/integration/test_real_llm_language.py::TestRealLLMLanguageCommunication::test_real_llm_situation_reading_with_russian_language -v -s
```

### Skip LLM Tests (for CI/CD without API keys)
```bash
SKIP_LLM_TESTS=1 pytest plugins/taro/tests/unit/...
```

Or set environment variable before running:
```bash
export SKIP_LLM_TESTS=1
make pre-commit-quick
```

## Test Coverage

### Language Tests
- ✅ Russian (ru) - Cyrillic characters
- ✅ German (de) - German compound words
- ✅ French (fr) - Accented characters
- ✅ Spanish (es) - Tildes

### Communication Tests
- ✅ Situation reading endpoint
- ✅ Follow-up question endpoint
- ✅ Language instruction in prompt
- ✅ Error handling with invalid credentials

## What These Tests Validate

### 1. Language Parameter in Real LLM Call
```
Frontend sends: language: "ru"
    ↓
Route receives and passes to service
    ↓
Service converts: "ru" → "Русский (Russian)"
    ↓
PromptService renders: "RESPOND IN {{language}} LANGUAGE."
    ↓
Final prompt sent to LLM: "RESPOND IN Русский (Russian) LANGUAGE. ..."
    ↓
Real LLM API receives the instruction
    ↓
LLM responds in Russian ✅
```

### 2. Configuration Loading
Tests verify:
- `vbwd-backend/plugins/config.json` loads correctly
- LLM API credentials are present
- Prompt templates contain language variable placeholders
- PromptService can render templates with language

### 3. Error Handling
Tests verify:
- LLMError properly raised for invalid credentials
- Graceful handling when API unreachable
- Timeout handling for slow API responses

## Expected Output

When you run the tests with `-s` flag, you'll see actual LLM responses:

```
✅ Russian LLM Response:
Карты говорят... [Russian Tarot reading response]

✅ German LLM Response:
Die Karten sprechen... [German Tarot reading response]

✅ French LLM Response:
Les cartes parlent... [French Tarot reading response]
```

## Important Notes

1. **These tests use real API credits** - Each test call uses tokens/credits from your LLM API account
2. **Responses may vary** - LLM responses are non-deterministic, so assertions are lenient
3. **Manual inspection recommended** - Review actual responses to validate language quality
4. **Skip in CI/CD** - Set `SKIP_LLM_TESTS=1` in CI pipelines to avoid API costs
5. **Timeout considerations** - Tests have 60-second timeout for LLM API responses

## Configuration File Structure

The tests load configuration from:

```json
{
  "taro": {
    "llm_api_endpoint": "https://api.deepseek.com",
    "llm_api_key": "sk-...",
    "llm_model": "deepseek-reasoner",
    "llm_temperature": 0.8,
    "llm_max_tokens": 200,
    "situation_reading_template": "...",
    "card_explanation_template": "...",
    "follow_up_question_template": "..."
  }
}
```

## Troubleshooting

### Tests Skip with "LLM credentials not configured"
**Solution**: Verify `vbwd-backend/plugins/config.json` has:
- `llm_api_endpoint` set to valid URL
- `llm_api_key` set to valid credentials

### LLMError: "Connection refused"
**Solution**: Ensure LLM API endpoint is accessible from your network

### LLMError: "Invalid API key"
**Solution**: Update `llm_api_key` in config.json with valid credentials

### Timeout errors
**Solution**: Increase timeout value in test (default is 60 seconds)

## Future Enhancements

- [ ] Language detection in LLM responses (NLP-based validation)
- [ ] Response quality scoring per language
- [ ] Token usage tracking per language
- [ ] Latency benchmarking for different languages
- [ ] Cost analysis by language

---

**Last Updated**: February 19, 2026
**Status**: ✅ Ready for Production Use
