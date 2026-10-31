import type { ModelDefaults } from './api';

const MODELS = {
  'muse-spark-1.3': { provider: 'meta', name: 'Muse Spark 1.3' },
  'gpt-6.1-sol': { provider: 'openai', name: 'GPT-6.1 Sol' },
  'gemini-4-argon': { provider: 'google', name: 'Gemini 4 Argon' },
  'claude-opus-5-5': { provider: 'anthropic', name: 'Claude Opus 5.5' },
} as const;

export type ModelDefaultsView = {
  status: 'ready' | 'blocked' | 'unknown';
  profile: ModelDefaults['profile'] | null;
  participants: ModelDefaults['participants'];
};

export function modelName(model: string): string {
  return Object.prototype.hasOwnProperty.call(MODELS, model) ? MODELS[model as keyof typeof MODELS].name : '';
}

// A ready badge requires a complete, consistent server response. Missing or
// contradictory readiness must never become a client-side "ready" default.
export function modelDefaultsView(input: unknown): ModelDefaultsView {
  const unknown: ModelDefaultsView = { status: 'unknown', profile: null, participants: [] };
  if (!input || typeof input !== 'object' || Array.isArray(input)) return unknown;
  const doc = input as Partial<ModelDefaults>;
  if ((doc.profile !== 'collaborative' && doc.profile !== 'legacy') ||
      typeof doc.ready !== 'boolean' || doc.requires_api_key !== false ||
      doc.default_builder !== 'muse-spark-1.3' || !Array.isArray(doc.participants) ||
      doc.participants.length === 0 || doc.participants.length > 4) return unknown;
  const participants: ModelDefaults['participants'] = [];
  const identities = new Set<string>();
  for (const item of doc.participants) {
    if (!item || typeof item !== 'object' ||
        !['builder', 'planner', 'critic'].includes(item.role) ||
        typeof item.model !== 'string' || typeof item.configured !== 'boolean') return unknown;
    if (!Object.prototype.hasOwnProperty.call(MODELS, item.model)) return unknown;
    const model = MODELS[item.model as keyof typeof MODELS];
    if (!model || item.provider !== model.provider) return unknown;
    const identity = `${item.role}:${item.model}`;
    if (identities.has(identity)) return unknown;
    identities.add(identity);
    participants.push({role: item.role, provider: item.provider, model: item.model, configured: item.configured});
  }
  const expected = doc.profile === 'collaborative'
    ? ['builder:muse-spark-1.3', 'planner:gpt-6.1-sol', 'planner:gemini-4-argon', 'critic:claude-opus-5-5']
    : ['builder:muse-spark-1.3', 'critic:muse-spark-1.3'];
  const critic = doc.profile === 'collaborative' ? 'claude-opus-5-5' : 'muse-spark-1.3';
  const complete = doc.default_critic === critic && identities.size === expected.length && expected.every(id => identities.has(id));
  return {
    profile: doc.profile,
    participants,
    status: doc.ready && complete && participants.every(item => item.configured) ? 'ready' : 'blocked',
  };
}
