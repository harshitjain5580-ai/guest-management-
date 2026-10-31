let guests = [];
let filter = 'all';
let rsvpStatus = 'confirmed';
let rsvpParty = 1;
const $ = (id) => document.getElementById(id);
const copy = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function getStats() {
  const confirmed = guests.filter(g => g.status === 'confirmed');
  const declined = guests.filter(g => g.status === 'declined');
  const pending = guests.filter(g => g.status === 'pending');
  return { total: guests.length, confirmed: confirmed.length, declined: declined.length, pending: pending.length, headcount: confirmed.reduce((sum, g) => sum + g.party, 0), households: new Set(guests.map(g => g.household)).size };
}

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const payload = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.error || 'Something went wrong. Please try again.');
  return payload;
}

function friendlyDate(value) {
  const d = new Date(value); return Number.isNaN(d) ? value : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function render() {
  const s = getStats();
  $('totalInvited').textContent = s.total;
  $('householdText').textContent = copy(s.households, 'household', 'households');
  $('confirmedCount').textContent = s.confirmed;
  $('confirmedHeadcount').textContent = s.headcount;
  $('declinedCount').textContent = s.declined;
  $('pendingCount').textContent = s.pending;
  $('pendingMessage').textContent = s.pending ? `${copy(s.pending, 'guest needs', 'guests need')} a nudge` : 'No follow-up needed';
  $('planHeadcount').textContent = s.headcount;
  const replied = s.confirmed + s.declined;
  const rate = s.total ? Math.round((replied / s.total) * 100) : 0;
  $('responseRate').textContent = `${rate}% replied`;
  $('confirmedBar').style.width = `${s.total ? (s.confirmed / s.total) * 100 : 0}%`;
  $('declinedBar').style.width = `${s.total ? (s.declined / s.total) * 100 : 0}%`;
  $('reminderTitle').textContent = s.pending ? `${copy(s.pending, 'gentle reminder', 'gentle reminders')} to send` : 'Every guest has replied';
  $('reminderCopy').textContent = s.pending ? `A warm nudge could help you lock in the last details for ${copy(s.pending, 'guest', 'guests')}.` : 'Your RSVP list is complete. Time to focus on the lovely details.';
  $('cardRemindButton').textContent = s.pending ? 'Review pending guests →' : 'View guest list →';
  const visible = filter === 'all' ? guests : guests.filter(g => g.status === filter);
  $('guestRows').innerHTML = visible.map(g => `<tr><td>${escapeHtml(g.name)}<span class="guest-meta">${escapeHtml(g.household)}</span></td><td>${g.status === 'declined' ? '—' : g.party}</td><td><span class="status ${g.status}">${label(g.status)}</span></td><td>${friendlyDate(g.updated)}</td></tr>`).join('') || '<tr><td colspan="4">No guests in this view.</td></tr>';
}
function label(status) { return status === 'confirmed' ? 'Confirmed' : status === 'declined' ? 'Not attending' : 'Awaiting reply'; }
function escapeHtml(value) { const el = document.createElement('div'); el.textContent = value; return el.innerHTML; }
function toast(message) { const t = $('toast'); t.textContent = message; t.classList.add('show'); clearTimeout(window.toastTimeout); window.toastTimeout = setTimeout(() => t.classList.remove('show'), 3200); }

async function refresh() { guests = await request('/api/guests'); render(); }
document.querySelectorAll('.filter').forEach(button => button.addEventListener('click', async () => { filter = button.dataset.filter; document.querySelectorAll('.filter').forEach(b => b.classList.toggle('active', b === button)); await refresh(); }));
$('addGuestButton').addEventListener('click', () => $('guestDialog').showModal());
$('openRsvpButton').addEventListener('click', () => $('rsvpDialog').showModal());
$('remindButton').addEventListener('click', () => sendReminders());
$('cardRemindButton').addEventListener('click', () => { document.querySelector('[data-filter="pending"]').click(); document.querySelector('#guests').scrollIntoView({ behavior: 'smooth' }); });

$('guestForm').addEventListener('submit', async event => { event.preventDefault(); const name = $('guestName').value.trim(); if (!name) return; try { const guest = await request('/api/guests', { method: 'POST', body: JSON.stringify({ name, household: $('guestHousehold').value.trim(), party: Number($('guestParty').value), status: $('guestStatus').value }) }); $('guestDialog').close(); event.target.reset(); $('guestParty').value = 1; filter = 'all'; document.querySelectorAll('.filter').forEach(b => b.classList.toggle('active', b.dataset.filter === 'all')); await refresh(); toast(`${guest.name} was added. Their unique RSVP link is ready.`); } catch (error) { toast(error.message); } });
document.querySelectorAll('.rsvp-choice').forEach(b => b.addEventListener('click', () => { rsvpStatus = b.dataset.rsvp; document.querySelectorAll('.rsvp-choice').forEach(x => x.classList.toggle('selected', x === b)); $('partyControl').style.opacity = rsvpStatus === 'declined' ? '.45' : '1'; }));
$('minus').addEventListener('click', () => { rsvpParty = Math.max(1, rsvpParty - 1); $('partyNumber').textContent = rsvpParty; });
$('plus').addEventListener('click', () => { rsvpParty = Math.min(12, rsvpParty + 1); $('partyNumber').textContent = rsvpParty; });
$('rsvpForm').addEventListener('submit', event => { event.preventDefault(); $('rsvpDialog').close(); toast('This dashboard preview shows the guest experience. Send a guest their unique RSVP link from the server API.'); });
async function sendReminders() { try { const result = await request('/api/reminders', { method: 'POST', body: '{}' }); await refresh(); toast(result.message); } catch (error) { toast(error.message); } }
$('exportButton').addEventListener('click', () => window.location.assign('/api/export.csv'));
refresh().catch(error => { toast(`Could not load the app: ${error.message}`); });
