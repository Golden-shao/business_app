const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const text = fs.readFileSync(path.join(__dirname, '../workflows/ai-review.yaml'), 'utf8').replaceAll('\r\n', '\n');
const body = text.split('          script: |\n')[1].split('\n').map(line => line.startsWith('            ') ? line.slice(12) : line).join('\n');
const evaluate = new (Object.getPrototypeOf(async function(){}).constructor)('github', 'context', 'core', body);
const trusted = {login: 'chatgpt-codex-connector[bot]', type: 'Bot'};
const review = (state, extra = {}) => ({id: 1, state, user: trusted, commit_id: 'current-head', html_url: 'https://github.com/review/1', ...extra});
const summary = (overrides = {}, extra = {}) => ({user: trusted, html_url: 'https://github.com/comment/2',
  body: '<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 '+JSON.stringify({code_review: {
    commit_sha: 'current-head', status: 'completed', has_any_findings: false, has_unresolved_findings: false, ...overrides}})+' -->', ...extra});

async function run(reviews = [], comments = []) {
  let result;
  const github = {
    rest: {pulls: {get: async () => ({data: {head: {sha: 'current-head'}, html_url: 'https://github.com/pr/1'}}), listReviews: () => {}},
           issues: {listComments: () => {}}, repos: {createCommitStatus: async status => {result = status;}}},
    paginate: async method => method === github.rest.pulls.listReviews ? reviews : comments,
  };
  await evaluate(github, {repo: {owner: 'owner', repo: 'repo'}, payload: {pull_request: {number: 1}}}, {notice() {}});
  assert.equal(result.sha, 'current-head');
  assert.equal(result.context, 'Harbor / AI review');
  return result.state;
}

test('formal reviews bind the Bot identity and exact commit', async () => {
  assert.equal(await run([review('APPROVED')]), 'success');
  assert.equal(await run([]), 'pending');
  assert.equal(await run([review('COMMENTED')]), 'pending');
  assert.equal(await run([review('APPROVED', {commit_id: 'old-head'})]), 'pending');
  assert.equal(await run([review('APPROVED', {user: {login: 'contributor', type: 'User'}})]), 'pending');
});

test('new findings and dismissals revoke a formal pass', async () => {
  assert.equal(await run([review('APPROVED'), review('CHANGES_REQUESTED')]), 'failure');
  assert.equal(await run([review('APPROVED'), review('DISMISSED')]), 'pending');
  assert.equal(await run([review('APPROVED'), review('COMMENTED')]), 'pending');
});

test('only a completed, clean, current-head authenticated Bot summary passes', async () => {
  assert.equal(await run([], [summary()]), 'success');
  assert.equal(await run([], [summary({commit_sha: 'old-head'})]), 'pending');
  assert.equal(await run([], [summary({status: 'running'})]), 'pending');
  assert.equal(await run([], [summary({has_any_findings: null})]), 'pending');
  assert.equal(await run([], [summary({has_any_findings: true, has_unresolved_findings: true})]), 'failure');
  assert.equal(await run([], [summary({}, {user: {login: trusted.login, type: 'User'}})]), 'pending');
  assert.equal(await run([], [summary({}, {user: {login: 'contributor', type: 'User'}})]), 'pending');
  assert.equal(await run([], [summary({}, {body: 'LGTM 👍'})]), 'pending');
});

test('a summary cannot override an explicit changes-requested review', async () => {
  assert.equal(await run([review('CHANGES_REQUESTED')], [summary()]), 'pending');
});

test('write-capable publisher never uses PR-controlled review events or checkout', () => {
  const eventSection = text.split('permissions:')[0];
  assert.ok(eventSection.includes('  pull_request_target:'));
  assert.ok(eventSection.includes('  issue_comment:'));
  assert.ok(!eventSection.includes('  pull_request_review:'));
  assert.ok(!text.includes('uses: actions/checkout'));
});
