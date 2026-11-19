/**
 * Notice scanner: start the GitHub scan as soon as a newspaper lands in Drive NoticeScanner/Inbox.
 *
 * Lives at script.google.com (your Google account, free). Every minute it looks in the Inbox; when
 * a new file is there it tells GitHub to run "Notice scan". Nothing is sent anywhere else.
 *
 * One-time setup (README, "Automatic start"):
 *   1. Project Settings -> Script Properties -> add GITHUB_TOKEN = your fine-grained token
 *      (repository: Work only; permission: Actions = Read and write).
 *   2. Choose the function "setup" at the top and press Run. Allow the permissions it asks for.
 *      It checks the token and the Inbox, then switches on the every-minute check.
 */

const INBOX_ID = '17wOA1TY3c5vjGwRAJFOw_FEC7Caqb2mg';   // NoticeScanner/Inbox
const REPO = 'hridhaykapoor7831/Work';
const WORKFLOW = 'notice-scan.yml';
const PHOTO_SETTLE_MS = 2 * 60 * 1000;   // loose photos: wait until none arrived for 2 minutes
const SCANNABLE = /\.(pdf|jpe?g|png)$/i;

function setup() {
  const branch = defaultBranch_();             // proves the token works
  const n = inboxFiles_().length;              // proves the Inbox is reachable
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'checkInbox')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('checkInbox').timeBased().everyMinutes(1).create();
  Logger.log('Ready. GitHub branch: ' + branch + '. Files in Inbox now: ' + n +
             '. The Inbox is now checked every minute.');
}

function checkInbox() {
  const props = PropertiesService.getScriptProperties();
  const started = JSON.parse(props.getProperty('STARTED') || '[]');
  const files = inboxFiles_();
  const ids = files.map(f => f.getId());
  // forget files that have left the Inbox (scanned and moved to Processed)
  const stillThere = started.filter(id => ids.indexOf(id) >= 0);
  const fresh = files.filter(f => stillThere.indexOf(f.getId()) < 0);
  if (!fresh.length) {
    props.setProperty('STARTED', JSON.stringify(stillThere));
    return;
  }
  const hasPdf = fresh.some(f => /\.pdf$/i.test(f.getName()));
  if (!hasPdf) {
    // photos arrive one by one; start only once the last one has been there a while
    const newest = Math.max.apply(null, fresh.map(f => f.getDateCreated().getTime()));
    if (Date.now() - newest < PHOTO_SETTLE_MS) return;
  }
  dispatch_();
  props.setProperty('STARTED', JSON.stringify(stillThere.concat(fresh.map(f => f.getId()))));
}

function inboxFiles_() {
  const out = [];
  const it = DriveApp.getFolderById(INBOX_ID).getFiles();
  while (it.hasNext()) {
    const f = it.next();
    if (!f.isTrashed() && SCANNABLE.test(f.getName())) out.push(f);
  }
  return out;
}

function dispatch_() {
  const res = github_('post', '/actions/workflows/' + WORKFLOW + '/dispatches', { ref: defaultBranch_() });
  if (res.getResponseCode() !== 204) {
    throw new Error('GitHub refused to start the scan (' + res.getResponseCode() + '): ' + res.getContentText());
  }
}

function defaultBranch_() {
  const res = github_('get', '');
  if (res.getResponseCode() !== 200) {
    throw new Error('GitHub token not accepted (' + res.getResponseCode() + '). Check GITHUB_TOKEN in Script Properties.');
  }
  return JSON.parse(res.getContentText()).default_branch;
}

function github_(method, path, body) {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Add GITHUB_TOKEN under Project Settings -> Script Properties first.');
  const opts = {
    method: method,
    muteHttpExceptions: true,
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28' },
  };
  if (body) { opts.contentType = 'application/json'; opts.payload = JSON.stringify(body); }
  return UrlFetchApp.fetch('https://api.github.com/repos/' + REPO + path, opts);
}
