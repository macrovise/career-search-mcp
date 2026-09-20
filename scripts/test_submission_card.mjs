// Exercise the actual embedded script without a browser or third-party packages.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../src/jobsearch_mcp/submission_card.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.hidden = false; this.disabled = false; this.textContent = ''; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.textContent = ''; }
  setAttribute() {}
  focus() {}
}

const role = { id: 'role-123', title: 'Support Engineer', company: 'Example', application_tracking: { submission_status: 'not_submitted' } };
const submittedRole = { ...role, application_tracking: { submission_status: 'submitted' } };
const structured = value => ({ structuredContent: value });

function harness() {
  const elements = { jobs: new Element('main'), connection: new Element('p') };
  const messages = [];
  const timers = new Map();
  let listener;
  let timerId = 0;
  const parent = { postMessage: message => messages.push(message) };
  vm.runInNewContext(script, {
    document: { getElementById: id => elements[id], createElement: tag => new Element(tag), createTextNode: text => ({ textContent: text }) },
    window: { parent, addEventListener: (_type, callback) => { listener = callback; } },
    setTimeout: callback => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: id => timers.delete(id),
  });
  const receive = message => listener({ source: parent, data: { jsonrpc: '2.0', ...message } });
  const render = (jobs = [role], writable = true) => receive({ method: 'ui/notifications/tool-result', params: structured({ jobs, writes_enabled: writable }) });
  const controls = () => {
    const article = elements.jobs.children[0];
    const [heading, company, button, confirmation, status] = article.children;
    return { heading, company, button, confirmation, status, yes: confirmation.children[1], cancel: confirmation.children[3] };
  };
  const calls = () => messages.filter(message => message.method === 'tools/call');
  const reply = (call, result) => receive({ id: call.id, result });
  reply(messages[0], {});
  return { render, controls, calls, reply, receive, elements };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test('rendering and cancelling confirmation never writes', () => {
  const app = harness();
  app.render();
  const ui = app.controls();
  assert.equal(ui.button.textContent, 'Mark as submitted');
  assert.equal(ui.confirmation.hidden, true);
  assert.equal(app.calls().length, 0);
  ui.button.onclick();
  assert.equal(ui.confirmation.hidden, false);
  assert.equal(app.calls().length, 0);
  ui.cancel.onclick();
  assert.equal(ui.confirmation.hidden, true);
  assert.equal(ui.button.hidden, false);
  assert.equal(app.calls().length, 0);
});

test('confirmation writes exact role, then requires verified read-back before Submitted', async () => {
  const app = harness();
  app.render();
  const ui = app.controls();
  ui.button.onclick();
  const action = ui.yes.onclick();
  const write = app.calls()[0];
  assert.equal(write.params.name, 'mark_as_applied');
  assert.equal(write.params.arguments.job_id, role.id);
  assert.equal(write.params.arguments.confirmation.confirmed, true);
  assert.equal(write.params.arguments.confirmation.submitted_at, null);
  assert.equal(write.params.arguments.confirmation.evidence_source, 'user_confirmation');
  assert.equal(ui.yes.disabled, true);
  app.reply(write, structured(submittedRole));
  await settle();
  assert.equal(ui.button.textContent, 'Mark as submitted');
  const read = app.calls()[1];
  assert.equal(read.params.name, 'get_job_detail');
  assert.equal(read.params.arguments.job_id, role.id);
  app.reply(read, structured(submittedRole));
  await action;
  assert.equal(ui.button.textContent, 'Submitted ✓');
  assert.equal(ui.button.disabled, true);
  assert.equal(ui.confirmation.hidden, true);
  assert.equal(app.calls().length, 2);
});

for (const [label, result] of [
  ['unsubmitted read-back', structured(role)],
  ['wrong role read-back', structured({ ...submittedRole, id: 'different-role' })],
  ['missing structured evidence', {}],
  ['tool error', { isError: true }],
]) {
  test(`${label} does not claim successful submission`, async () => {
    const app = harness();
    app.render();
    const ui = app.controls();
    const action = ui.yes.onclick();
    app.reply(app.calls()[0], structured(submittedRole));
    await settle();
    app.reply(app.calls()[1], result);
    await action;
    assert.equal(ui.button.textContent, 'Mark as submitted');
    assert.equal(ui.status.className, 'error');
    assert.notEqual(ui.status.textContent, 'Saved in your shared application register.');
  });
}

test('write rejection does not read back or claim success', async () => {
  const app = harness();
  app.render();
  const ui = app.controls();
  const action = ui.yes.onclick();
  app.receive({ id: app.calls()[0].id, error: { message: 'Permission denied' } });
  await action;
  assert.equal(app.calls().length, 1);
  assert.equal(ui.status.textContent, 'Permission denied');
  assert.equal(ui.button.textContent, 'Mark as submitted');
});

test('repeated submitted render disables button without any writes', () => {
  const app = harness();
  for (let count = 0; count < 2; count++) {
    app.render([submittedRole]);
    assert.equal(app.controls().button.textContent, 'Submitted ✓');
    assert.equal(app.controls().button.disabled, true);
  }
  assert.equal(app.calls().length, 0);
});

test('read-only result disables submission control', () => {
  const app = harness();
  app.render([role], false);
  assert.equal(app.controls().button.disabled, true);
  assert.equal(app.controls().status.textContent, 'Write access is disabled.');
  assert.equal(app.calls().length, 0);
});
