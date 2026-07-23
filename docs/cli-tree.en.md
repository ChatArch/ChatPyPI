# CLI Tree

The CLI tree is the most direct command entry in the ChatPyPI documentation. Readers should be able to see the supported surface from this tree before jumping into publishing flows, the interface tree, or command-specific notes.

Status contract:

- **Implemented**: the command path is registered and maps to a Python function or service layer.
- **Verified**: the command is covered by tests, local smoke, CI, or real PyPI/Pages practice.
- **Planned / checkpoint**: the command only carries entry and boundary notes; do not present it as an automated tutorial.

## Current Command Tree

```text
chatpypi                                      # Python package lifecycle and PyPI operation entry
├── --version                                 # Print the current ChatPyPI version
├── init                                      # Compatibility entry: create a src-layout Python package
├── build                                     # Compatibility entry: build wheel / sdist
├── check                                     # Compatibility entry: validate dist with twine check
├── upload                                    # Compatibility entry: upload dist with manual token env
├── probe                                     # Compatibility entry: check whether a package name is available
├── pkg                                      # Package lifecycle group
│   ├── init                                  # Create default or chatarch scaffold packages
│   ├── build                                 # Build wheel / sdist and optionally clean dist
│   ├── check                                 # Validate built distributions
│   ├── upload                                # Upload with token / password env values
│   └── probe                                 # Query PyPI package-name conflicts
├── auth                                     # Session, account, and assisted bootstrap flows
│   ├── login                                 # Login with username/password/TOTP and write session token
│   ├── logout                                # Clear the local session token
│   ├── whoami                                # Read back the current account summary from session
│   ├── register                              # Planned / checkpoint: account registration
│   ├── verify-email                          # Planned / checkpoint: email verification
│   ├── setup-2fa                             # Planned / checkpoint: 2FA initialization
│   ├── recovery-codes                        # Planned / checkpoint: recovery-code handling
│   └── session                               # Env-backed session management
│       ├── show                              # Print a non-sensitive session summary
│       ├── export                            # Planned / checkpoint: export session
│       ├── import                            # Planned / checkpoint: import session
│       └── clear                             # Clear session token
├── profile                                  # Planned: local ChatPyPI profile management
│   ├── list                                  # Planned: list profiles
│   ├── show                                  # Planned: show non-sensitive profile fields
│   ├── use                                   # Planned: switch active profile
│   ├── create                                # Planned: create profile
│   └── delete                                # Planned: delete profile
├── config                                   # Planned: local config key/value management
│   ├── list                                  # Planned: list config values
│   ├── get                                   # Planned: read config value
│   ├── set                                   # Planned: write config value
│   └── unset                                 # Planned: delete config value
├── project                                  # PyPI project views for the logged-in account
│   ├── list                                  # Implemented: read project list
│   └── show                                  # Planned: show one project detail
├── publisher                                # Trusted Publisher reads and writes
│   ├── list                                  # Implemented: read account-level publisher status
│   ├── detail                                # Implemented: read project-level publisher status
│   ├── add-github                            # Implemented: add/idempotently verify active GitHub publisher
│   ├── pending-list                          # Implemented: read pending publishers
│   ├── pending-add                           # Implemented: add a pending-publisher exception
│   └── pending-remove                        # Implemented: clean a pending publisher
├── token                                    # Planned / checkpoint: PyPI API token management
│   ├── list                                  # Planned: list token summaries without revealing tokens
│   ├── create                                # Planned: create token and store one-time secret safely
│   └── revoke                                # Planned: revoke token after confirmation
├── doctor                                   # Local config and session diagnostics
│   └── check                                 # Implemented: check config, session, and safety boundaries
└── docs                                     # Documentation links and examples
    ├── links                                 # Print core documentation links
    ├── examples                              # Print common example commands
    └── open                                  # Print a documentation URL for a topic
```

## Capability Groups

<div class="grid cards" markdown>

- **Package Lifecycle**

    `pkg init/build/check/upload/probe` is the base loop for creating, building, checking, uploading, and probing Python packages.

- **Logged-in Reads**

    `auth whoami`, `project list`, and `publisher list/detail` depend on a session and only print non-sensitive summaries and structured state.

- **Publisher Writes**

    `publisher add-github` targets active Trusted Publisher setup for existing PyPI projects. Pending commands are only for real pending exceptions or cleanup.

- **Checkpoint Flows**

    Registration, email verification, 2FA, and token create/revoke flows remain checkpoint-heavy. Docs should describe boundaries, not fake full automation.

</div>

## Update Rules

- Every implemented command must map back to a Python function or service layer.
- If a command writes remote state, document credentials, permissions, dry-run/checkpoint behavior, or confirmation boundaries.
- Planned entries should only carry boundary notes, not executable tutorials.
- When the CLI tree gains a command, update README, the interface tree, tests, and related flow pages together.
