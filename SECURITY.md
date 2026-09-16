# Security policy

RosterTheory is an alpha local CLI. No hosted service, account system, or
automatic Sleeper write operation is provided. Treat generated reports and
league configuration as private; keep `FANTASYPROS_API_KEY` in an environment
variable or ignored `.env`, never in an issue, log, or commit.

Security fixes are considered for the current source release line. There is
no promised support period for historical versions or Python versions below
3.11.

If you find a vulnerability, do not publish exploit details, secrets, or real
league data in a public issue. Use GitHub's private vulnerability-reporting
feature for this repository if it is enabled; otherwise open a minimal issue
requesting a confidential contact channel, without vulnerability details. Share
the affected version, reproduction with synthetic inputs, and potential impact.
We will acknowledge and triage reports as capacity permits, coordinate a fix
and disclosure, and avoid claiming a response-time guarantee we cannot meet.

If an API key or private league file was exposed, revoke or replace the key
through its provider and remove the data from public view. Deleting a file in a
new commit does not erase it from Git history.
