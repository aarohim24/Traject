const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// Timeout constants (ms)
const TIMEOUT_UPLOAD    = 120_000;
const TIMEOUT_GENERATE  = 180_000;  // LLM + embedding can take longer on cold starts
const TIMEOUT_EVALUATE  = 120_000;
const TIMEOUT_AGENT     = 30_000;
const TIMEOUT_DEBRIEF   = 60_000;

async function request(method, path, body = null, isFormData = false, timeoutMs = 60_000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const opts = {
      method,
      headers: isFormData ? {} : { 'Content-Type': 'application/json' },
      body: isFormData ? body : body ? JSON.stringify(body) : null,
      signal: controller.signal,
    };

    const res = await fetch(`${BASE_URL}${path}`, opts);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
    return data;
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('Request timed out. The server took too long to respond. Please try again.');
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  uploadResume: (file) => {
    const form = new FormData();
    form.append('file', file);
    return request('POST', '/upload-resume', form, true, TIMEOUT_UPLOAD);
  },

  generateQuestions: (payload) =>
    request('POST', '/generate-questions', payload, false, TIMEOUT_GENERATE),

  evaluateAnswer: (payload) =>
    request('POST', '/evaluate-answer', payload, false, TIMEOUT_EVALUATE),

  agentNextMove: (payload) =>
    request('POST', '/agent/next-move', payload, false, TIMEOUT_AGENT),

  sessionDebrief: (payload) =>
    request('POST', '/session-debrief', payload, false, TIMEOUT_DEBRIEF),

  getLearnerProfile: (candidateId) =>
    request('GET', `/learner/${candidateId}/profile`, null, false, 30_000),
};
