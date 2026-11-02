import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/worker.js';

function assetsRecorder() {
  const requests = [];
  return {
    requests,
    env: { ASSETS: { fetch: async (req) => {
      requests.push(new URL(req.url));
      return new Response('asset', { status: 200 });
    } } },
  };
}

test('mounts app under subpath without requiring a hostname in code', async () => {
  const { env, requests } = assetsRecorder();
  const res = await worker.fetch(new Request('https://example.org/segment-morph/assets/app.js?v=1'), env);
  assert.equal(res.status, 200);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].pathname, '/assets/app.js');
  assert.equal(requests[0].search, '?v=1');
});

test('trailing slash redirect retains arbitrary hostname and query', async () => {
  const { env, requests } = assetsRecorder();
  const res = await worker.fetch(new Request('https://example.org/segment-morph?x=1'), env);
  assert.equal(res.status, 308);
  assert.equal(res.headers.get('location'), 'https://example.org/segment-morph/?x=1');
  assert.equal(requests.length, 0);
});

test('mount root resolves to index through assets binding', async () => {
  const { env, requests } = assetsRecorder();
  const res = await worker.fetch(new Request('https://example.org/segment-morph/'), env);
  assert.equal(res.status, 200);
  assert.equal(requests[0].pathname, '/');
});

test('works directly at workers.dev root for initial preview', async () => {
  const { env, requests } = assetsRecorder();
  const res = await worker.fetch(new Request('https://worker.example.workers.dev/assets/app.js'), env);
  assert.equal(res.status, 200);
  assert.equal(requests[0].pathname, '/assets/app.js');
});
