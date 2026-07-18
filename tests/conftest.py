import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Hermetic git: CI runners and containers have no git identity configured, and
# git commit/merge refuse to run without one ("Please tell me who you are").
# The env vars cover author + committer without touching any real config.
os.environ.setdefault("GIT_AUTHOR_NAME", "meldq-tests")
os.environ.setdefault("GIT_AUTHOR_EMAIL", "meldq-tests@example.invalid")
os.environ.setdefault("GIT_COMMITTER_NAME", "meldq-tests")
os.environ.setdefault("GIT_COMMITTER_EMAIL", "meldq-tests@example.invalid")
