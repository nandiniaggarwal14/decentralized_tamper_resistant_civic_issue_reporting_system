const listEl = document.getElementById('issue-list');
const messageEl = document.getElementById('message');
const voterId = getOrCreateVoterId();
const votingInProgress = new Set();
const issuesById = new Map();

function showMessage(text, isError = false) {
  messageEl.textContent = text;
  messageEl.style.color = isError ? '#b91c1c' : '#047857';
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function getOrCreateVoterId() {
  const existing = localStorage.getItem('voter_id');
  if (existing) {
    return existing;
  }

  const generated =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `voter-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  localStorage.setItem('voter_id', generated);
  return generated;
}

function normalizeIssue(issue) {
  const upvotes = Number(issue?.votes?.upvotes ?? 0);
  const downvotes = Number(issue?.votes?.downvotes ?? 0);
  const userVote = issue?.votes?.user_vote || null;

  return {
    ...issue,
    votes: {
      upvotes,
      downvotes,
      score: upvotes - downvotes,
      user_vote: userVote,
    },
  };
}

function setIssues(issues) {
  issuesById.clear();
  for (const issue of issues) {
    issuesById.set(issue.id, normalizeIssue(issue));
  }
}

function getIssueVoteView(issue) {
  const upvotes = issue.votes?.upvotes ?? 0;
  const downvotes = issue.votes?.downvotes ?? 0;
  const userVote = issue.votes?.user_vote || null;
  const score = issue.votes?.score ?? upvotes - downvotes;

  return {
    upvotes,
    downvotes,
    userVote,
    score,
    upActive: userVote === 'up' ? 'active-up' : '',
    downActive: userVote === 'down' ? 'active-down' : '',
  };
}

function applyVoteMutation(issue, nextVote) {
  const previousVote = issue.votes?.user_vote || null;
  let upvotes = Number(issue.votes?.upvotes ?? 0);
  let downvotes = Number(issue.votes?.downvotes ?? 0);

  if (previousVote === 'up') {
    upvotes -= 1;
  } else if (previousVote === 'down') {
    downvotes -= 1;
  }

  if (nextVote === 'up') {
    upvotes += 1;
  } else if (nextVote === 'down') {
    downvotes += 1;
  }

  issue.votes = {
    upvotes,
    downvotes,
    score: upvotes - downvotes,
    user_vote: nextVote,
  };
}

function applyServerVoteState(issue, data) {
  const upvotes = Number(data?.upvotes ?? 0);
  const downvotes = Number(data?.downvotes ?? 0);

  issue.votes = {
    upvotes,
    downvotes,
    score: Number(data?.score ?? upvotes - downvotes),
    user_vote: data?.user_vote || null,
  };
}

function updateIssueVoteUI(issueId) {
  const issue = issuesById.get(issueId);
  if (!issue) {
    return;
  }

  const card = listEl.querySelector(`[data-issue-id="${CSS.escape(issueId)}"]`);
  if (!card) {
    return;
  }

  const { upvotes, downvotes, score, upActive, downActive } = getIssueVoteView(issue);
  const upButton = card.querySelector('[data-role="upvote-btn"]');
  const downButton = card.querySelector('[data-role="downvote-btn"]');
  const scoreEl = card.querySelector('[data-role="vote-score"]');

  if (upButton) {
    upButton.textContent = `▲ ${upvotes}`;
    upButton.classList.toggle('active-up', Boolean(upActive));
  }

  if (downButton) {
    downButton.textContent = `▼ ${downvotes}`;
    downButton.classList.toggle('active-down', Boolean(downActive));
  }

  if (scoreEl) {
    scoreEl.textContent = `Score: ${score}`;
  }
}

function renderIssues(issues) {
  if (!issues.length) {
    listEl.innerHTML = '<p>No reports yet.</p>';
    return;
  }

  listEl.innerHTML = issues
    .map((issue) => {
      const { upvotes, downvotes, score, upActive, downActive } = getIssueVoteView(issue);
      const imagePart = issue.image_url
        ? `<img class="issue-thumb" src="${issue.image_url}" alt="Issue image for ${escapeHtml(issue.title)}" />`
        : '<div class="issue-thumb issue-thumb-empty">No Image</div>';

      return `
        <article class="issue issue-card" data-issue-id="${escapeHtml(issue.id)}">
          <div class="issue-card-header">
            ${imagePart}
            <div class="issue-main">
              <h3>${escapeHtml(issue.title)}</h3>
              <p class="meta"><strong>Area:</strong> ${escapeHtml(issue.area)} • <strong>Status:</strong> ${escapeHtml(issue.status)}</p>
              <p class="meta"><strong>Category:</strong> ${escapeHtml(issue.category)}</p>
            </div>
            <div class="vote-panel">
              <button class="vote-btn ${upActive}" data-role="upvote-btn" data-vote-type="up" data-issue-id="${escapeHtml(issue.id)}">▲ ${upvotes}</button>
              <button class="vote-btn ${downActive}" data-role="downvote-btn" data-vote-type="down" data-issue-id="${escapeHtml(issue.id)}">▼ ${downvotes}</button>
              <p class="vote-score" data-role="vote-score">Score: ${score}</p>
            </div>
          </div>
          <div class="issue-actions">
            <button class="details-btn" data-issue-id="${escapeHtml(issue.id)}" data-expanded="false">View Details</button>
          </div>
          <div id="details-${escapeHtml(issue.id)}" class="issue-details" hidden>
            <p>${escapeHtml(issue.description)}</p>
            <p class="meta"><strong>Location:</strong> ${escapeHtml(issue.location.latitude)}, ${escapeHtml(issue.location.longitude)}</p>
            <p class="meta"><strong>Address:</strong> ${escapeHtml(issue.address || 'N/A')}</p>
            <p class="meta"><strong>Reporter:</strong> ${escapeHtml(issue.reporter.name)} ${issue.reporter.contact ? `(${escapeHtml(issue.reporter.contact)})` : ''}</p>
            ${issue.image_url ? `<img src="${issue.image_url}" alt="Issue image for ${escapeHtml(issue.title)}" />` : ''}
          </div>
        </article>
      `;
    })
    .join('');
}

async function loadIssues() {
  try {
    const response = await fetch(`/api/issues?voter_id=${encodeURIComponent(voterId)}`);
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || 'Failed to fetch issues');
    }
    const issues = Array.isArray(result.data) ? result.data.map(normalizeIssue) : [];
    setIssues(issues);
    renderIssues(issues);
  } catch (error) {
    showMessage(error.message, true);
  }
}

async function voteOnIssue(issueId, voteType) {
  if (votingInProgress.has(issueId)) {
    return;
  }

  const issue = issuesById.get(issueId);
  if (!issue) {
    return;
  }

  const previousVote = issue.votes?.user_vote || null;
  const nextVote = previousVote === voteType ? null : voteType;
  const snapshot = {
    upvotes: issue.votes?.upvotes ?? 0,
    downvotes: issue.votes?.downvotes ?? 0,
    score: issue.votes?.score ?? 0,
    user_vote: previousVote,
  };

  applyVoteMutation(issue, nextVote);
  updateIssueVoteUI(issueId);

  votingInProgress.add(issueId);

  try {
    const response = await fetch(`/api/issues/${issueId}/vote`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        voter_id: voterId,
        vote_type: voteType,
      }),
    });

    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || 'Failed to record vote');
    }

    applyServerVoteState(issue, result.data || {});
    updateIssueVoteUI(issueId);
    showMessage('Vote updated successfully.');
  } catch (error) {
    issue.votes = { ...snapshot };
    updateIssueVoteUI(issueId);
    showMessage(error.message, true);
  } finally {
    votingInProgress.delete(issueId);
  }
}

listEl.addEventListener('click', async (event) => {
  const voteButton = event.target.closest('.vote-btn');
  if (voteButton) {
    const issueId = voteButton.getAttribute('data-issue-id');
    const voteType = voteButton.getAttribute('data-vote-type');
    if (issueId && voteType) {
      await voteOnIssue(issueId, voteType);
    }
    return;
  }

  const detailsButton = event.target.closest('.details-btn');
  if (detailsButton) {
    const issueId = detailsButton.getAttribute('data-issue-id');
    const details = document.getElementById(`details-${issueId}`);
    if (!details) {
      return;
    }

    const expanded = detailsButton.getAttribute('data-expanded') === 'true';
    details.hidden = expanded;
    detailsButton.setAttribute('data-expanded', String(!expanded));
    detailsButton.textContent = expanded ? 'View Details' : 'Hide Details';
  }
});

loadIssues();
