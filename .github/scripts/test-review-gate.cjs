const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const text = fs.readFileSync(path.join(__dirname, '../workflows/ai-review.yaml'), 'utf8');
const body = text.split('          script: |\n')[1].split('\n').map(line => line.startsWith('            ') ? line.slice(12) : line).join('\n');
const evaluate = new (Object.getPrototypeOf(async function(){}).constructor)('github', 'context', 'core', body);
const trusted = {login: 'chatgpt-codex-connector[bot]', type: 'Bot'};
const review = (state, extra = {}) => ({id: 1, state, user: trusted, commit_id: 'current-head', html_url: 'https://github.com/review/1', ...extra});

async function run(reviews) {
  let result;
  const github = {
    rest: {pulls: {get: async () => ({data: {head: {sha: 'current-head'}, html_url: 'https://github.com/pr/1'}}), listReviews: () => {}},
           repos: {createCommitStatus: async status => {result = status;}}},
    paginate: async () => reviews,
  };
  await evaluate(github, {repo: {owner: 'owner', repo: 'repo'}, payload: {pull_request: {number: 1}}}, {notice() {}});
  assert.equal(result.sha, 'current-head');
  assert.equal(result.context, 'Harbor / AI review');
  return result.state;
}

test('only a formal independent approval of the exact head passes', async () => {
  assert.equal(await run([review('APPROVED')]), 'success');
  assert.equal(await run([]), 'pending');
  assert.equal(await run([review('COMMENTED')]), 'pending');
  assert.equal(await run([review('APPROVED', {commit_id: 'old-head'})]), 'pending');
  assert.equal(await run([review('APPROVED', {user: {login: 'contributor', type: 'User'}})]), 'pending');
  assert.equal(await run([review('APPROVED', {user: {...trusted, type: 'User'}})]), 'pending');
});

test('new findings or a dismissed approval revoke a previous pass', async () => {
  assert.equal(await run([review('APPROVED'), review('CHANGES_REQUESTED')]), 'failure');
  assert.equal(await run([review('APPROVED'), review('DISMISSED')]), 'pending');
  assert.equal(await run([review('APPROVED'), review('COMMENTED')]), 'pending');
});
