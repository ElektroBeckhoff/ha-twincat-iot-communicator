# CLAUDE.md

Read and follow [AGENTS.md](AGENTS.md) for every task in this repository. It is
imported below so it is always in context.

@AGENTS.md

## Most important rule

The integration is built for the **official Beckhoff TF6730 IoT Communicator
interface only**. Every decision (features, mappings, defaults, names, tests,
docs, changelog, commit messages, PR texts) must be derived from the official
protocol. Do not mention, depend on, or tailor anything to a specific private or
third-party PLC library or repository, including the repository owner's own
libraries. If a requirement is only known from such a library, it is not a
requirement for this integration.
