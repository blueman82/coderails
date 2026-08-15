# Codex lifecycle enforcement

`lifecycle.py` is the supported JSON lifecycle boundary. It is mechanical for
the state it receives, but cannot enforce events that Codex does not deliver;
the host must invoke it before accepting completion.
