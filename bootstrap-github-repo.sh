#!/usr/bin/env bash
set -euo pipefail

REPO_NAME="${REPO_NAME:-vgm-etf-committee}"
REPO_DESCRIPTION="${REPO_DESCRIPTION:-Communication repository for the VGM ETF allocation simulator}"
PRIVATE="${PRIVATE:-true}"
GITHUB_OWNER="${GITHUB_OWNER:-vguchtw}"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "ERROR: export GITHUB_TOKEN with permission to create repositories and write contents." >&2
  exit 1
fi

api() {
  curl --fail-with-body --silent --show-error \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "$@"
}

if api "https://api.github.com/repos/${GITHUB_OWNER}/${REPO_NAME}" >/dev/null 2>&1; then
  echo "Repository ${GITHUB_OWNER}/${REPO_NAME} already exists."
else
  api -X POST "https://api.github.com/user/repos" \
    -d "{\"name\":\"${REPO_NAME}\",\"description\":\"${REPO_DESCRIPTION}\",\"private\":${PRIVATE},\"auto_init\":true}" \
    >/dev/null
  echo "Created ${GITHUB_OWNER}/${REPO_NAME}."
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

git clone "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_OWNER}/${REPO_NAME}.git" "$tmp/repo"
cd "$tmp/repo"

mkdir -p policy requests/pending requests/processed \
  decisions/pending decisions/accepted decisions/rejected status

for dir in requests/pending requests/processed decisions/pending decisions/accepted decisions/rejected status; do
  touch "$dir/.gitkeep"
done

cp /app/policy.example.json policy/policy.json 2>/dev/null || true

cat > README.md <<'EOF'
# VGM ETF Committee

GitHub communication channel between the VGM ETF Bridge container and the ChatGPT allocation committee.

The server owns state and execution. ChatGPT may only add proposed JSON decisions under `decisions/pending/`.
EOF

git config user.name "${GIT_AUTHOR_NAME:-VGM ETF Bridge}"
git config user.email "${GIT_AUTHOR_EMAIL:-automation@vgm-consultancy.be}"
git add -A
if ! git diff --cached --quiet; then
  git commit -m "Initialize VGM ETF communication repository"
  git push origin main
fi

echo "Repository ready: https://github.com/${GITHUB_OWNER}/${REPO_NAME}"
