# Publish your copy on GitHub

Publish **this repository folder**, not the parent workspace or a running
installation's data directories. The source archive contains code, fictional
examples and documentation; it contains no installation configuration or records.

The project uses the MIT license. Keep `LICENSE` and third-party notices with the
source. Enable private vulnerability reporting under GitHub's security settings
if you want contributors to report issues privately.

## Inspect before the first commit

```sh
git status --short
git status --short --ignored
git diff --cached --stat
git ls-files
```

Review the actual staged files. `.env`, `.secrets`, `.local`, generated trust
roots, exports and test screenshots must not be staged. Only `.env.example`
and the empty `deploy/public-ca/.gitkeep` belong in source. Ignore rules do not
remove secrets already committed in earlier history. This source project starts
with fresh history; do not import a personal installation's old history.

## Upload

Create an empty GitHub repository named `expo-buddy`, without adding another
README or license. If this folder was extracted from the ZIP, initialize Git:

```sh
git init -b main
git add .
git diff --cached --stat
git commit -m "Initial Expo Buddy release"
git remote add origin https://github.com/YOUR-USERNAME/expo-buddy.git
git push -u origin main
```

If Git is already initialized, skip `git init`. Replace `YOUR-USERNAME` with your
actual account. Configure your own Git author identity if Git asks. No access
token or account name is included in the project.

After upload, check the Actions tab. The workflow runs unit checks and builds the
frontend. Docker builds and browser/recovery checks should also be run locally
before a release. Add release notes that identify actual tested platforms and
known limitations; do not describe every workflow as stable just because CI passes.
