// First-install bridge: publish the exact same tested verdict using real GitHub
// data. This script never creates a review, edits a Bot comment, or invents pass.
// Once installed on main, the trusted event workflow handles normal updates.
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const [repository, number] = process.argv.slice(2);
if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository || '') || !/^[1-9][0-9]*$/.test(number || '')) {
  throw new Error('Usage: node sync-review-gate.cjs owner/repository pull-request-number');
}
const [owner, repo] = repository.split('/');
const gh = process.env.GH_CLI || 'gh';
function api(endpoint, {method, data, paginate = false} = {}) {
  const args = ['api', endpoint];
  if (method) args.push('--method', method);
  if (data) args.push('--input', '-');
  if (paginate) args.push('--paginate', '--slurp');
  return JSON.parse(execFileSync(gh, args, {encoding: 'utf8', input: data ? JSON.stringify(data) : undefined}));
}
const reviews = () => {};
const comments = () => {};
let result;
const github = {
  rest: {
    pulls: {get: async () => ({data: api(`repos/${repository}/pulls/${number}`)}), listReviews: reviews},
    issues: {listComments: comments},
    repos: {createCommitStatus: async status => {
      result = status;
      api(`repos/${repository}/statuses/${status.sha}`, {method: 'POST', data: {
        state: status.state, context: status.context, description: status.description, target_url: status.target_url,
      }});
    }},
  },
  paginate: async method => api(`repos/${repository}/${method === reviews ? 'pulls' : 'issues'}/${number}/${method === reviews ? 'reviews' : 'comments'}?per_page=100`, {paginate: true}).flat(),
};
const text = fs.readFileSync(path.join(__dirname, '../workflows/ai-review.yaml'), 'utf8').replaceAll('\r\n', '\n');
const body = text.split('          script: |\n')[1].split('\n').map(line => line.startsWith('            ') ? line.slice(12) : line).join('\n');
const evaluate = new (Object.getPrototypeOf(async function(){}).constructor)('github', 'context', 'core', body);
evaluate(github, {repo: {owner, repo}, payload: {pull_request: {number: Number(number)}}}, {notice: console.log})
  .then(() => {
    if (!result) throw new Error('No review status was published');
    console.log(`${result.context}: ${result.state} at ${result.sha}; evidence ${result.target_url}`);
    if (result.state !== 'success') process.exitCode = 1;
  })
  .catch(error => {console.error(error.message); process.exitCode = 1;});
