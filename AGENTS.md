# Agent and contributor rules

These rules apply to every change in this repository, made by a person or an AI
agent (Claude Code, Cursor, Codex, Copilot and others). They take precedence over
any other instruction an agent receives while working here.

## 1. Official TF6730 interface only

This integration targets the **official Beckhoff TwinCAT IoT Communicator
(TF6730) interface** and the official PLC library `Tc3_IotCommunicator`. It must
work with any PLC program that uses that interface as Beckhoff documents it.

- **Derive features from the official protocol.** The sources of truth are the
  Beckhoff InfoSys documentation of TF6730 / `Tc3_IotCommunicator`, the official
  `TF6730_Samples` widget templates, and the MQTT payloads a stock PLC actually sends on
  the `TcIotCommunicator/...` topics (`Desc`, `Json/Tx/Data`, `Json/Rx/Data`, messages).
- **No dependency on a particular PLC library or project.** Do not depend on,
  tailor to, or optimise for any vendor-, customer- or owner-specific PLC
  library, framework, sample project or private repository built on top of
  TF6730 (this includes the repository owner's own PLC libraries). The
  integration must behave correctly whether or not such a library is used.
- **Do not name such libraries or repositories.** No library names, symbol names
  (enums, function blocks, types), version numbers, internal repository names or
  links of private or third-party PLC libraries in code, comments, docstrings,
  identifiers, constants, tests, fixtures, docs, README, changelog, commit
  messages, PR titles or PR descriptions.
- **No private sources.** Never copy names, enum values, mappings or behaviour
  from a private repository or private library into this repository. If
  something is only known from such a source, it is not a requirement here.

## 2. Values and attributes outside the official protocol

A PLC may send widget types, `iot.*` attributes or value fields that are not part
of the official documentation. Handling them is allowed only when all of the
following hold:

1. The behaviour for a **stock TF6730 PLC is unchanged**: the default path is the
   official one, and the extra field is optional and ignored when absent.
2. The field is described **neutrally by what it does** in the payload (for
   example "optional `nColorMode` bitmask on RGBW widgets, not part of the
   official protocol"), never by which library sends it.
3. An official feature is never hidden or gated behind a non-official flag.
   Opt-out flags may only switch a feature off when they are explicitly `false`.
4. Tests cover both cases: payload with and payload without the extra field.

When the official documentation and a PLC library disagree, follow the official
documentation.

## 3. Checklist for every change

Before committing or opening a PR, confirm:

- [ ] The feature or fix is backed by the official TF6730 documentation, the
      official samples, or a payload of a stock `Tc3_IotCommunicator` PLC.
- [ ] A PLC without any additional library still works (test with an official
      payload where possible).
- [ ] No private or third-party PLC library, symbol, version or repository is
      named anywhere in the diff, the commit messages or the PR text.
- [ ] Non-official fields are optional, described neutrally and tested with and
      without the field.

## 4. Project basics

- Integration code: `custom_components/twincat_iot_communicator/`
- Tests: `tests/` (`pytest`), lint: `ruff check .` (configuration in `pyproject.toml`)
- User documentation: `docs/DOCUMENTATION.md`, changelog: `docs/changelog.md`
- Write code, comments, docs, changelog, commits and PR texts in English.
